import hashlib
import json
from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase, override_settings
from django.utils import timezone
from .models import (
    ApiUser,
    AccessToken,
    Role,
    Event,
    Schedule,
    SyncRun,
    AuditLog,
    ApiRequestLog,
    AccessRule,
)
from .rbac import OPERATOR_PERMISSIONS
from .credentials import configure_client
from .provider_secrets import decrypt_token
from .password_policy import valid_password
from .services import enqueue, process_one


class IdentityTests(TestCase):
    def setUp(self):
        self.master = configure_client(
            "master-client", "MasterPass1!", sympla_token="master-provider-test-only"
        )
        self.master.is_superuser, self.master.role = True, Role.objects.get(
            name="master"
        )
        self.master.save()
        self.master_header = self.header(self.master)
        self.role = Role.objects.create(name="Custom operator")
        self.role.permissions.set(OPERATOR_PERMISSIONS + ["identity:edit"])

    def header(self, api_account):
        api_account.refresh_from_db()
        value = f"test-{api_account .identifier }-{api_account .credential_version }"
        AccessToken.objects.update_or_create(
            token_hash=hashlib.sha256(value.encode()).hexdigest(),
            defaults={
                "api_account": api_account,
                "credential_version": api_account.credential_version,
                "expires_at": timezone.now() + timedelta(hours=1),
            },
        )
        return {"HTTP_AUTHORIZATION": "Bearer " + value}

    def request(self, method, path, data=None, header=None):
        return getattr(self.client, method)(
            path,
            data=json.dumps(data) if data is not None else "",
            content_type="application/json",
            **(header or self.master_header),
        )

    def create_api_account(self, name="alice", provider="alice-provider-test-only"):
        result = self.request(
            "post",
            "/api-users",
            {
                "client_id": name,
                "role_identifier": str(self.role.identifier),
                "sympla_token": provider,
            },
        )
        self.assertEqual(result.status_code, 201, result.content)
        return (
            ApiUser.objects.get(identifier=result.json()["identifier"]),
            result.json(),
        )

    def test_create_lookup_and_write_only_provider_secret(self):
        api_account, result = self.create_api_account()
        self.assertTrue(valid_password(result["client_secret"]))
        self.assertEqual(decrypt_token(api_account), "alice-provider-test-only")
        self.assertNotIn("alice-provider-test-only", api_account.sympla_token_encrypted)
        for path in [
            f"/api-users/{api_account .identifier }",
            f"/api/users/{api_account .identifier }",
        ]:
            public = self.client.get(path, **self.master_header)
            self.assertEqual(public.status_code, 200)
            for secret in [
                "alice-provider-test-only",
                result["client_secret"],
                api_account.client_secret_hash,
                api_account.sympla_token_encrypted,
            ]:
                self.assertNotIn(secret, public.content.decode())
        logs = str(list(AuditLog.objects.values())) + str(
            list(ApiRequestLog.objects.values())
        )
        self.assertNotIn("alice-provider-test-only", logs)
        self.assertNotIn(result["client_secret"], logs)
        issued = self.client.post(
            "/api/v1/token/",
            {
                "grant_type": "client_credentials",
                "client_id": "alice",
                "client_secret": result["client_secret"],
            },
            content_type="application/json",
        )
        self.assertEqual(issued.status_code, 200)

    def test_missing_provider_and_privilege_injection_rejected(self):
        for extra in [
            {},
            {"sympla_token": ""},
            {"sympla_token": "test-token", "is_superuser": True},
        ]:
            result = self.request(
                "post",
                "/api-users",
                {
                    "client_id": "bad-user",
                    "role_identifier": str(self.role.identifier),
                    **extra,
                },
            )
            self.assertEqual(result.status_code, 400)
        self.assertFalse(ApiUser.objects.filter(client_id="bad-user").exists())

    def test_master_is_protected_and_cannot_be_assigned(self):
        api_account, _ = self.create_api_account()
        for path, method, data in [
            (f"/api-users/{self .master .identifier }", "patch", {"is_active": False}),
            (f"/api-users/{self .master .identifier }", "delete", None),
            (
                f"/api-users/{self .master .identifier }/role",
                "put",
                {"role_identifier": str(self.role.identifier)},
            ),
            (f"/api-users/{self .master .identifier }/credentials", "post", {}),
            (f"/credentials/{self .master .credential_identifier }", "delete", None),
            (
                f"/roles/{self .master .role .identifier }/permissions",
                "put",
                {"permissions": []},
            ),
            (
                f"/api-users/{api_account .identifier }/role",
                "put",
                {"role_identifier": str(self.master.role.identifier)},
            ),
        ]:
            self.assertEqual(self.request(method, path, data).status_code, 403, path)
        self.master.refresh_from_db()
        self.assertTrue(self.master.is_superuser and self.master.is_active)

    def test_ordinary_users_cannot_administer_or_inspect_other_identities(self):
        alice, _ = self.create_api_account()
        bob, _ = self.create_api_account("bob", "bob-provider-test-only")
        header = self.header(alice)
        self.assertEqual(
            self.client.get("/me", **header).json()["identifier"], str(alice.identifier)
        )
        self.assertEqual(self.client.get("/api-users", **header).status_code, 403)
        self.assertEqual(
            self.client.get(f"/api-users/{bob .identifier }", **header).status_code, 403
        )
        self.assertEqual(
            self.request(
                "post", "/roles", {"name": "escalate", "permissions": ["events:read"]}, header
            ).status_code,
            403,
        )
        self.assertEqual(
            self.request(
                "put",
                f"/api-users/{alice .identifier }/permissions",
                {"permissions": ["events:read"]},
                header,
            ).status_code,
            403,
        )

    def test_four_permissions_are_independent_and_changes_revoke_tokens(self):
        self.role.permissions.set(["schedules:write"])
        api_account, _ = self.create_api_account()
        header = self.header(api_account)
        created = self.request(
            "post", "/api/v1/schedules/", {"time": "09:30", "timezone": "UTC"}, header
        )
        self.assertEqual(created.status_code, 201)
        schedule_id = created.json()["id"]
        self.assertEqual(self.client.get("/api/v1/events/", **header).status_code, 403)
        self.assertEqual(
            self.request(
                "patch", f"/api/v1/schedules/{schedule_id }/", {"active": False}, header
            ).status_code,
            403,
        )
        self.assertEqual(
            self.request(
                "delete", f"/api/v1/schedules/{schedule_id }/", header=header
            ).status_code,
            403,
        )
        result = self.request(
            "put",
            f"/roles/{self .role .identifier }/permissions",
            {"permissions": ["events:read", "schedules:edit", "schedules:delete"]},
        )
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.client.get("/api/v1/events/", **header).status_code, 401)
        header = self.header(api_account)
        self.assertEqual(self.client.get("/api/v1/events/", **header).status_code, 200)
        self.assertEqual(
            self.request(
                "patch", f"/api/v1/schedules/{schedule_id }/", {"active": False}, header
            ).status_code,
            200,
        )
        self.assertEqual(
            self.request(
                "delete", f"/api/v1/schedules/{schedule_id }/", header=header
            ).status_code,
            204,
        )
        self.assertEqual(
            self.request("post", "/api/v1/sync/", {}, header).status_code, 403
        )

    def test_delegated_identity_actions_are_independent(self):
        operator, _ = self.create_api_account("delegated")
        target, _ = self.create_api_account("target")
        empty = Role.objects.create(name="No permissions")
        for action in ("write", "edit", "delete"):
            self.role.permissions.set([f"identity:{action}"])
            header = self.header(operator)
            result = self.request("post", "/api-users", {
                "client_id": f"created-{action}", "role_identifier": str(empty.identifier),
                "sympla_token": "isolated-provider-token",
            }, header)
            self.assertEqual(result.status_code, 201 if action == "write" else 403)
            result = self.request("patch", f"/api-users/{target.identifier}", {"is_active": True}, header)
            self.assertEqual(result.status_code, 200 if action == "edit" else 403)
            result = self.request("delete", f"/api-users/{target.identifier}", header=header)
            self.assertEqual(result.status_code, 204 if action == "delete" else 403)
            self.assertEqual(self.request("get", "/roles", header=header).status_code, 403)
            self.assertEqual(self.request("get", "/api/v1/events/", header=header).status_code, 403)

    def test_delegated_role_creation_and_escalation_boundary(self):
        operator, _ = self.create_api_account("role-manager")
        self.role.permissions.set(["roles:write", "events:read"])
        header = self.header(operator)
        result = self.request("post", "/roles", {"name": "Event reader", "permissions": ["events:read"]}, header)
        self.assertEqual(result.status_code, 201)
        role_id = result.json()["identifier"]
        self.assertEqual(self.request("patch", f"/roles/{role_id}", {"name": "Forbidden edit"}, header).status_code, 403)
        self.assertEqual(self.request("delete", f"/roles/{role_id}", header=header).status_code, 403)
        self.assertEqual(self.request("post", "/roles", {"name": "Escalation", "permissions": ["identity:write"]}, header).status_code, 403)
        self.assertFalse(Role.objects.filter(name="Escalation").exists())
        self.role.permissions.set(["roles:edit", "events:read"])
        header = self.header(operator)
        self.assertEqual(self.request("put", f"/roles/{role_id}/permissions", {"permissions": ["identity:write"]}, header).status_code, 403)
        self.assertEqual(self.request("patch", f"/roles/{role_id}", {"name": "Edited reader"}, header).status_code, 200)
        self.role.permissions.set(["roles:delete"])
        self.assertEqual(self.request("delete", f"/roles/{role_id}", header=self.header(operator)).status_code, 204)

    def test_every_section_requires_its_own_read_permission(self):
        operator, _ = self.create_api_account("section-reader")
        routes = {"identity": "/api-users", "roles": "/roles", "authorization": "/permissions",
                  "schedules": "/api/v1/schedules/", "synchronization": "/api/v1/sync-runs/",
                  "events": "/api/v1/events/", "audit": "/api/v1/audit-logs/"}
        for allowed in routes:
            self.role.permissions.set([f"{allowed}:read"])
            header = self.header(operator)
            for section, path in routes.items():
                with self.subTest(allowed=allowed, section=section):
                    self.assertEqual(self.request("get", path, header=header).status_code, 200 if section == allowed else 403)
            self.assertEqual(self.request("get", "/me", header=header).status_code, 200)

    def test_token_generation_does_not_require_resource_permissions(self):
        self.role.permissions.clear()
        api_account, created = self.create_api_account("token-only")
        result = self.client.post("/api/v1/token/", data=json.dumps({
            "grant_type": "client_credentials", "client_id": api_account.client_id,
            "client_secret": created["client_secret"],
        }), content_type="application/json")
        self.assertEqual(result.status_code, 200)
        header = {"HTTP_AUTHORIZATION": "Bearer " + result.json()["access_token"]}
        self.assertEqual(self.request("get", "/me", header=header).status_code, 200)
        self.assertEqual(self.request("get", "/api/v1/events/", header=header).status_code, 403)

    def test_individual_grants_preserve_role_and_rule_crud(self):
        self.role.permissions.set([])
        api_account, _ = self.create_api_account()
        result = self.request(
            "post",
            "/access-rules",
            {"api_user_identifier": str(api_account.identifier), "permission": "events:read"},
        )
        self.assertEqual(result.status_code, 201)
        rule_id = result.json()["identifier"]
        self.assertEqual(
            self.client.get("/api/v1/events/", **self.header(api_account)).status_code,
            200,
        )
        self.assertEqual(
            self.request("delete", f"/access-rules/{rule_id }").status_code, 204
        )
        self.assertEqual(
            self.client.get("/api/v1/events/", **self.header(api_account)).status_code,
            403,
        )
        original = api_account.role_id
        result = self.request(
            "put",
            f"/api-users/{api_account .identifier }/permissions",
            {"permissions": ["events:read", "schedules:write"]},
        )
        self.assertEqual(result.status_code, 200)
        api_account.refresh_from_db()
        self.assertEqual(api_account.role_id, original)
        self.assertEqual(set(result.json()["permissions"]), {"events:read", "schedules:write"})

    def test_role_lifecycle_and_relationship_conflicts(self):
        result = self.request(
            "post", "/roles", {"name": "Temporary", "permissions": ["events:read"]}
        )
        self.assertEqual(result.status_code, 201)
        role_id = result.json()["identifier"]
        self.assertEqual(
            self.request(
                "patch", f"/roles/{role_id }", {"description": "Updated"}
            ).status_code,
            200,
        )
        api_account, _ = self.create_api_account()
        self.assertEqual(
            self.request(
                "put",
                f"/api-users/{api_account .identifier }/role",
                {"role_identifier": role_id},
            ).status_code,
            200,
        )
        self.assertEqual(self.request("delete", f"/roles/{role_id }").status_code, 409)
        self.request(
            "put",
            f"/api-users/{api_account .identifier }/role",
            {"role_identifier": str(self.role.identifier)},
        )
        self.assertEqual(self.request("delete", f"/roles/{role_id }").status_code, 204)
        self.assertEqual(
            self.request(
                "post", "/roles", {"name": "Invalid", "permissions": ["admin"]}
            ).status_code,
            400,
        )

    def test_credential_issue_revoke_and_identity_status(self):
        api_account, original = self.create_api_account()
        old_header = self.header(api_account)
        result = self.request(
            "post", f"/api-users/{api_account .identifier }/credentials", {}
        )
        self.assertEqual(result.status_code, 201)
        self.assertNotEqual(result.json()["client_secret"], original["client_secret"])
        self.assertEqual(self.client.get("/me", **old_header).status_code, 401)
        self.assertEqual(
            self.request(
                "delete", "/credentials/" + result.json()["identifier"]
            ).status_code,
            204,
        )
        denied = self.client.post(
            "/api/v1/token/",
            {
                "grant_type": "client_credentials",
                "client_id": api_account.client_id,
                "client_secret": result.json()["client_secret"],
            },
            content_type="application/json",
        )
        self.assertEqual(denied.status_code, 401)
        run = enqueue(api_account.client_id, owner=api_account)
        self.assertEqual(
            self.request(
                "patch", f"/api-users/{api_account .identifier }", {"is_active": False}
            ).status_code,
            200,
        )
        run.refresh_from_db()
        self.assertEqual(run.status, "cancelled")

    @patch("core.integration_modules.sympla.connector.fetch_events")
    def test_provider_events_schedules_runs_and_logs_are_user_scoped(self, fetch):
        alice, _ = self.create_api_account()
        bob, _ = self.create_api_account("bob", "bob-provider-test-only")
        fetch.side_effect = [
            [{"id": "same-external-id", "name": "Alice event"}],
            [{"id": "same-external-id", "name": "Bob event"}],
        ]
        first = enqueue(alice.client_id, owner=alice)
        process_one()
        second = enqueue(bob.client_id, owner=bob)
        process_one()
        self.assertEqual(
            fetch.call_args_list[0].kwargs["token"], "alice-provider-test-only"
        )
        self.assertEqual(
            fetch.call_args_list[1].kwargs["token"], "bob-provider-test-only"
        )
        self.assertEqual(Event.objects.count(), 2)
        header = self.header(alice)
        events = self.client.get("/api/v1/events/", **header).json()["results"]
        self.assertEqual([e["data"]["name"] for e in events], ["Alice event"])
        foreign = Event.objects.get(owner=bob)
        self.assertEqual(
            self.client.get(
                f"/api/v1/events/{foreign .id }/versions/", **header
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(f"/api/v1/sync-runs/{second .pk }/", **header).status_code,
            404,
        )
        for api_account in [alice, bob]:
            response = self.request(
                "post",
                "/api/v1/schedules/",
                {"time": "09:30", "timezone": "UTC"},
                self.header(api_account),
            )
            self.assertEqual(response.status_code, 201)
        foreign_schedule = Schedule.objects.get(owner=bob)
        self.assertEqual(
            self.request(
                "delete", f"/api/v1/schedules/{foreign_schedule .pk }/", header=header
            ).status_code,
            404,
        )
        audit = self.client.get("/api/v1/audit-logs/", **header).json()["results"]
        self.assertNotIn("Bob event", str(audit))
        self.assertEqual(
            self.client.get("/api/v1/sync-runs/", **header).json()["count"], 1
        )

    @patch("core.integration_modules.sympla.connector.fetch_events")
    def test_provider_rotation_during_import_prevents_stale_commit(self, fetch):
        api_account, _ = self.create_api_account()
        enqueue(api_account.client_id, owner=api_account)

        def response(**kwargs):
            changed = self.request(
                "put",
                f"/api-users/{api_account .identifier }/sympla-token",
                {"sympla_token": "replacement-test-provider"},
            )
            self.assertEqual(changed.status_code, 200)
            return [{"id": "stale-result"}]

        fetch.side_effect = response
        result = process_one()
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_code, "owner_authorization_changed")
        self.assertFalse(Event.objects.filter(owner=api_account).exists())

    @override_settings(SYMPLA_API_KEY="master-global-provider-must-never-be-used")
    def test_an_ordinary_account_never_falls_back_to_global_provider(self):
        api_account = configure_client(
            "legacy-no-provider", "Testing1!", role=self.role
        )
        result = self.request("post", "/api/v1/sync/", {}, self.header(api_account))
        self.assertEqual(result.status_code, 503)
        self.assertFalse(SyncRun.objects.filter(owner=api_account).exists())

    def test_identity_audit_failure_rolls_back_account_and_secret(self):
        with patch(
            "core.identity.record", side_effect=RuntimeError("private internal context")
        ):
            result = self.request(
                "post",
                "/api-users",
                {
                    "client_id": "must-not-exist",
                    "role_identifier": str(self.role.identifier),
                    "sympla_token": "private-provider-value",
                },
            )
        self.assertEqual(result.status_code, 500)
        self.assertFalse(ApiUser.objects.filter(client_id="must-not-exist").exists())
        self.assertNotIn(
            "private-provider-value", str(list(ApiRequestLog.objects.values()))
        )
