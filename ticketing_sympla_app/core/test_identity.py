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
        self.role.permissions.set(["read", "write", "edit", "delete"])

    def header(self, user):
        user.refresh_from_db()
        value = f"test-{user.identifier}-{user.credential_version}"
        AccessToken.objects.update_or_create(
            token_hash=hashlib.sha256(value.encode()).hexdigest(),
            defaults={
                "user": user,
                "credential_version": user.credential_version,
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

    def create_user(self, name="alice", provider="alice-provider-test-only"):
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
        user, result = self.create_user()
        self.assertTrue(valid_password(result["client_secret"]))
        self.assertEqual(decrypt_token(user), "alice-provider-test-only")
        self.assertNotIn("alice-provider-test-only", user.sympla_token_encrypted)
        for path in [f"/api-users/{user.identifier}", f"/api/users/{user.identifier}"]:
            public = self.client.get(path, **self.master_header)
            self.assertEqual(public.status_code, 200)
            for secret in [
                "alice-provider-test-only",
                result["client_secret"],
                user.client_secret_hash,
                user.sympla_token_encrypted,
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
        self.assertFalse(ApiUser.objects.filter(username="bad-user").exists())

    def test_master_is_protected_and_cannot_be_assigned(self):
        user, _ = self.create_user()
        for path, method, data in [
            (f"/api-users/{self.master.identifier}", "patch", {"is_active": False}),
            (f"/api-users/{self.master.identifier}", "delete", None),
            (
                f"/api-users/{self.master.identifier}/role",
                "put",
                {"role_identifier": str(self.role.identifier)},
            ),
            (f"/api-users/{self.master.identifier}/credentials", "post", {}),
            (f"/credentials/{self.master.credential_identifier}", "delete", None),
            (
                f"/roles/{self.master.role.identifier}/permissions",
                "put",
                {"permissions": []},
            ),
            (
                f"/api-users/{user.identifier}/role",
                "put",
                {"role_identifier": str(self.master.role.identifier)},
            ),
        ]:
            self.assertEqual(self.request(method, path, data).status_code, 403, path)
        self.master.refresh_from_db()
        self.assertTrue(self.master.is_superuser and self.master.is_active)

    def test_ordinary_users_cannot_administer_or_inspect_other_identities(self):
        alice, _ = self.create_user()
        bob, _ = self.create_user("bob", "bob-provider-test-only")
        header = self.header(alice)
        self.assertEqual(
            self.client.get("/me", **header).json()["identifier"], str(alice.identifier)
        )
        self.assertEqual(self.client.get("/api-users", **header).status_code, 403)
        self.assertEqual(
            self.client.get(f"/api-users/{bob.identifier}", **header).status_code, 404
        )
        self.assertEqual(
            self.request(
                "post", "/roles", {"name": "escalate", "permissions": ["read"]}, header
            ).status_code,
            403,
        )
        self.assertEqual(
            self.request(
                "put",
                f"/api-users/{alice.identifier}/permissions",
                {"permissions": ["read"]},
                header,
            ).status_code,
            403,
        )

    def test_four_permissions_are_independent_and_changes_revoke_tokens(self):
        self.role.permissions.set(["write"])
        user, _ = self.create_user()
        header = self.header(user)
        created = self.request(
            "post", "/api/v1/schedules/", {"time": "09:30", "timezone": "UTC"}, header
        )
        self.assertEqual(created.status_code, 201)
        schedule_id = created.json()["id"]
        self.assertEqual(self.client.get("/api/v1/events/", **header).status_code, 403)
        self.assertEqual(
            self.request(
                "patch", f"/api/v1/schedules/{schedule_id}/", {"active": False}, header
            ).status_code,
            403,
        )
        self.assertEqual(
            self.request(
                "delete", f"/api/v1/schedules/{schedule_id}/", header=header
            ).status_code,
            403,
        )
        result = self.request(
            "put",
            f"/roles/{self.role.identifier}/permissions",
            {"permissions": ["read", "edit", "delete"]},
        )
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.client.get("/api/v1/events/", **header).status_code, 401)
        header = self.header(user)
        self.assertEqual(self.client.get("/api/v1/events/", **header).status_code, 200)
        self.assertEqual(
            self.request(
                "patch", f"/api/v1/schedules/{schedule_id}/", {"active": False}, header
            ).status_code,
            200,
        )
        self.assertEqual(
            self.request(
                "delete", f"/api/v1/schedules/{schedule_id}/", header=header
            ).status_code,
            204,
        )
        self.assertEqual(
            self.request("post", "/api/v1/sync/", {}, header).status_code, 403
        )

    def test_individual_grants_preserve_role_and_rule_crud(self):
        self.role.permissions.set([])
        user, _ = self.create_user()
        result = self.request(
            "post",
            "/access-rules",
            {"user_identifier": str(user.identifier), "permission": "read"},
        )
        self.assertEqual(result.status_code, 201)
        rule_id = result.json()["identifier"]
        self.assertEqual(
            self.client.get("/api/v1/events/", **self.header(user)).status_code, 200
        )
        self.assertEqual(
            self.request("delete", f"/access-rules/{rule_id}").status_code, 204
        )
        self.assertEqual(
            self.client.get("/api/v1/events/", **self.header(user)).status_code, 403
        )
        original = user.role_id
        result = self.request(
            "put",
            f"/api-users/{user.identifier}/permissions",
            {"permissions": ["read", "write"]},
        )
        self.assertEqual(result.status_code, 200)
        user.refresh_from_db()
        self.assertEqual(user.role_id, original)
        self.assertEqual(set(result.json()["permissions"]), {"read", "write"})

    def test_role_lifecycle_and_relationship_conflicts(self):
        result = self.request(
            "post", "/roles", {"name": "Temporary", "permissions": ["read"]}
        )
        self.assertEqual(result.status_code, 201)
        role_id = result.json()["identifier"]
        self.assertEqual(
            self.request(
                "patch", f"/roles/{role_id}", {"description": "Updated"}
            ).status_code,
            200,
        )
        user, _ = self.create_user()
        self.assertEqual(
            self.request(
                "put",
                f"/api-users/{user.identifier}/role",
                {"role_identifier": role_id},
            ).status_code,
            200,
        )
        self.assertEqual(self.request("delete", f"/roles/{role_id}").status_code, 409)
        self.request(
            "put",
            f"/api-users/{user.identifier}/role",
            {"role_identifier": str(self.role.identifier)},
        )
        self.assertEqual(self.request("delete", f"/roles/{role_id}").status_code, 204)
        self.assertEqual(
            self.request(
                "post", "/roles", {"name": "Invalid", "permissions": ["admin"]}
            ).status_code,
            400,
        )

    def test_credential_issue_revoke_and_identity_status(self):
        user, original = self.create_user()
        old_header = self.header(user)
        result = self.request("post", f"/api-users/{user.identifier}/credentials", {})
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
                "client_id": user.username,
                "client_secret": result.json()["client_secret"],
            },
            content_type="application/json",
        )
        self.assertEqual(denied.status_code, 401)
        run = enqueue(user.username, owner=user)
        self.assertEqual(
            self.request(
                "patch", f"/api-users/{user.identifier}", {"is_active": False}
            ).status_code,
            200,
        )
        run.refresh_from_db()
        self.assertEqual(run.status, "cancelled")

    @patch("core.services.fetch_events")
    def test_provider_events_schedules_runs_and_logs_are_user_scoped(self, fetch):
        alice, _ = self.create_user()
        bob, _ = self.create_user("bob", "bob-provider-test-only")
        fetch.side_effect = [
            [{"id": "same-external-id", "name": "Alice event"}],
            [{"id": "same-external-id", "name": "Bob event"}],
        ]
        first = enqueue(alice.username, owner=alice)
        process_one()
        second = enqueue(bob.username, owner=bob)
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
                f"/api/v1/events/{foreign.id}/versions/", **header
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(f"/api/v1/sync-runs/{second.pk}/", **header).status_code,
            404,
        )
        for user in [alice, bob]:
            response = self.request(
                "post",
                "/api/v1/schedules/",
                {"time": "09:30", "timezone": "UTC"},
                self.header(user),
            )
            self.assertEqual(response.status_code, 201)
        foreign_schedule = Schedule.objects.get(owner=bob)
        self.assertEqual(
            self.request(
                "delete", f"/api/v1/schedules/{foreign_schedule.pk}/", header=header
            ).status_code,
            404,
        )
        audit = self.client.get("/api/v1/audit-logs/", **header).json()["results"]
        self.assertNotIn("Bob event", str(audit))
        self.assertEqual(
            self.client.get("/api/v1/sync-runs/", **header).json()["count"], 1
        )

    @patch("core.services.fetch_events")
    def test_provider_rotation_during_import_prevents_stale_commit(self, fetch):
        user, _ = self.create_user()
        enqueue(user.username, owner=user)

        def response(**kwargs):
            changed = self.request(
                "put",
                f"/api-users/{user.identifier}/sympla-token",
                {"sympla_token": "replacement-test-provider"},
            )
            self.assertEqual(changed.status_code, 200)
            return [{"id": "stale-result"}]

        fetch.side_effect = response
        result = process_one()
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_code, "owner_authorization_changed")
        self.assertFalse(Event.objects.filter(owner=user).exists())

    @override_settings(SYMPLA_API_KEY="master-global-provider-must-never-be-used")
    def test_an_ordinary_account_never_falls_back_to_global_provider(self):
        user = configure_client("legacy-no-provider", "Testing1!", role=self.role)
        result = self.request("post", "/api/v1/sync/", {}, self.header(user))
        self.assertEqual(result.status_code, 503)
        self.assertFalse(SyncRun.objects.filter(owner=user).exists())

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
        self.assertFalse(ApiUser.objects.filter(username="must-not-exist").exists())
        self.assertNotIn(
            "private-provider-value", str(list(ApiRequestLog.objects.values()))
        )
