from django.test import SimpleTestCase, override_settings
from django.urls import resolve
from .openapi import SCHEMA


@override_settings(SECURE_SSL_REDIRECT=False, DOCS_ENABLED=True)
class DocumentationTests(SimpleTestCase):
    def test_schema_declares_section_permissions(self):
        paths = self.client.get("/openapi.json").json()["paths"]
        for path, method, permission in [
            ("/api-users", "post", "identity:write"),
            ("/api-users/{identifier}", "patch", "identity:edit"),
            ("/roles", "post", "roles:write"),
            ("/roles/{identifier}/permissions", "put", "roles:edit"),
            ("/permissions", "get", "authorization:read"),
            ("/api/v1/schedules/", "post", "schedules:write"),
            ("/api/v1/sync/", "post", "synchronization:write"),
            ("/api/v1/events/", "get", "events:read"),
            ("/api/v1/integrations/", "post", "integrations:write"),
            ("/api/v1/integrations/{integration_id}/", "patch", "integrations:edit"),
            ("/api/v1/events/{event_id}/observations/", "get", "events:read"),
        ]:
            self.assertEqual(paths[path][method]["x-required-permission"], permission)
        self.assertNotIn("x-required-permission", paths["/api/v1/token/"]["post"])

    def test_swagger_page_and_security(self):
        result = self.client.get("/docs/")
        self.assertEqual(result.status_code, 200)
        self.assertContains(result, "persistAuthorization: false")
        self.assertContains(result, "validatorUrl: null")
        self.assertContains(result, "request.credentials = 'omit'")
        self.assertNotContains(result, "https://")
        self.assertIn("connect-src 'self'", result["Content-Security-Policy"])
        self.assertEqual(self.client.get("/swagger/").status_code, 200)

    def test_schema_routes_and_bearer_scheme(self):
        spec = self.client.get("/openapi.json").json()
        self.assertEqual(spec["security"], [{"ClientCredentials": []}])
        self.assertEqual(
            spec["components"]["securitySchemes"]["ClientCredentials"]["flows"][
                "clientCredentials"
            ]["tokenUrl"],
            "/api/v1/token/",
        )
        self.assertEqual(spec["paths"]["/api/v1/token/"]["post"]["security"], [])
        self.assertEqual(spec["paths"]["/ping/"]["get"]["security"], [])
        for path in spec["paths"]:
            actual_path = (
                path.replace("{schedule_id}", "1")
                .replace("{statistic_id}", "1")
                .replace("{integration_id}", "00000000-0000-0000-0000-000000000001")
                .replace("{event_id}", "1")
                .replace("{run_id}", "00000000-0000-0000-0000-000000000001")
                .replace("{identifier}", "00000000-0000-0000-0000-000000000001")
            )
            self.assertIsNotNone(resolve(actual_path))
        self.assertEqual(
            spec["paths"]["/api/v1/sync/"]["post"]["requestBody"]["content"][
                "application/json"
            ]["example"],
            {},
        )

    def test_assets_are_local_and_allowlisted(self):
        for filename in ["swagger-ui-bundle.js", "swagger-ui.css"]:
            result = self.client.get("/docs/assets/" + filename)
            self.assertEqual(result.status_code, 200)
            self.assertGreater(len(b"".join(result.streaming_content)), 1000)
        self.assertEqual(self.client.get("/docs/assets/__init__.py").status_code, 404)

    @override_settings(DOCS_ENABLED=False)
    def test_docs_can_be_disabled_together(self):
        for path in [
            "/docs/",
            "/swagger/",
            "/openapi.json",
            "/docs/assets/swagger-ui-bundle.js",
        ]:
            self.assertEqual(self.client.get(path).status_code, 404)
