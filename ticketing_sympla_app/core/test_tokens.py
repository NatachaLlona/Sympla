import base64
import hashlib
import json
from datetime import timedelta
from urllib.parse import urlencode
from django.test import TestCase
from django.utils import timezone
from .credentials import configure_client
from .models import AccessToken, ApiRequestLog, AuditLog
from .password_policy import valid_password


class ClientCredentialsTests(TestCase):
    def setUp(self):
        self.api_account = configure_client(
            "test-client", "ClientSecret1!", can_write=True
        )

    def issue(self, **changes):
        return self.client.post(
            "/api/v1/token/",
            json.dumps(
                {
                    "grant_type": "client_credentials",
                    "client_id": "test-client",
                    "client_secret": "ClientSecret1!",
                    **changes,
                }
            ),
            content_type="application/json",
        )

    def test_token_flow_expiration_and_credential_rotation(self):
        result = self.issue()
        self.assertEqual(result.status_code, 200)
        payload = result.json()
        token = payload["access_token"]
        self.assertEqual(payload["expires_in"], 3600)
        self.assertEqual(payload["token_type"], "Bearer")
        self.assertEqual(result["Cache-Control"], "no-store")
        header = {"HTTP_AUTHORIZATION": "Bearer " + token}
        self.assertEqual(self.client.get("/api/v1/events/", **header).status_code, 200)
        stored = AccessToken.objects.get()
        self.assertEqual(stored.token_hash, hashlib.sha256(token.encode()).hexdigest())
        self.assertNotIn(token, str(list(ApiRequestLog.objects.values())))
        self.assertNotIn("ClientSecret1!", str(list(AuditLog.objects.values())))
        configure_client("test-client", "NewSecret12!", rotate=True)
        self.assertEqual(self.client.get("/api/v1/events/", **header).status_code, 401)
        self.assertEqual(self.issue().status_code, 401)
        issued = self.issue(client_secret="NewSecret12!").json()["access_token"]
        AccessToken.objects.filter(
            token_hash=hashlib.sha256(issued.encode()).hexdigest()
        ).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(
            self.client.get(
                "/api/v1/events/", HTTP_AUTHORIZATION="Bearer " + issued
            ).status_code,
            401,
        )

    def test_form_and_basic_auth_for_swagger(self):
        result = self.client.post(
            "/api/v1/token/",
            urlencode(
                {
                    "grant_type": "client_credentials",
                    "client_id": "test-client",
                    "client_secret": "ClientSecret1!",
                }
            ),
            content_type="application/x-www-form-urlencoded",
        )
        self.assertEqual(result.status_code, 200)
        basic = base64.b64encode(b"test-client:ClientSecret1!").decode()
        result = self.client.post(
            "/api/v1/token/",
            "grant_type=client_credentials",
            content_type="application/x-www-form-urlencoded",
            HTTP_AUTHORIZATION="Basic " + basic,
        )
        self.assertEqual(result.status_code, 200)

    def test_bad_credentials_grants_and_throttling(self):
        invalid = self.issue(client_secret="incorrect")
        self.assertEqual(invalid.status_code, 401)
        self.assertNotIn("Basic", invalid.get("WWW-Authenticate", ""))
        self.assertEqual(
            invalid.json()["error_description"],
            "Invalid API client ID or API client secret.",
        )
        self.assertEqual(self.issue(client_id="missing").status_code, 401)
        self.assertEqual(self.issue(grant_type="password").status_code, 400)
        self.assertEqual(self.issue(scope="admin").status_code, 400)
        for _ in range(6):
            self.issue(client_secret="incorrect")
        self.assertEqual(self.issue().status_code, 429)
        self.assertEqual(self.issue()["Retry-After"], "60")

    def test_legacy_static_tokens_are_not_accepted(self):
        legacy = "legacy-token-never-a-real-credential"
        self.api_account.token_hash = hashlib.sha256(legacy.encode()).hexdigest()
        self.api_account.save()
        self.assertEqual(
            self.client.get(
                "/api/v1/events/", HTTP_AUTHORIZATION="Bearer " + legacy
            ).status_code,
            401,
        )

    def test_password_policy(self):
        for value in [
            "short1!",
            "ALLUPPER1!",
            "alllower1!",
            "NoNumbers!",
            "NoSpecial1",
            "TooLongPassword12!",
            "With Space1!",
        ]:
            self.assertFalse(valid_password(value))
        self.assertTrue(valid_password("ValidPass1!"))
