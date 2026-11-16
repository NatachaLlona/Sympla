from django.urls import path
from . import views
from . import docs
from .token_views import token
from . import identity
from . import integrations, event_views
from . import statistics_views

urlpatterns = [
    path('api/v1/geographies/', statistics_views.geographies),
    path('api/v1/demographics/', statistics_views.statistics),
    path('api/v1/demographics/<int:statistic_id>/versions/', statistics_views.versions),
    path('api/v1/demographics/<int:statistic_id>/observations/', statistics_views.observations),
    path('api/v1/ibge/coverage/', statistics_views.coverage),
    path('api/v1/integration-providers/', integrations.providers),
    path('api/v1/integrations/', integrations.integrations),
    path('api/v1/integrations/<uuid:integration_id>/', integrations.integration_detail),
    path('api/v1/events/<int:event_id>/', event_views.event_detail),
    path('api/v1/events/<int:event_id>/observations/', event_views.observations),
    path("me", identity.me),
    path("api/v1/me/", identity.me),
    path("api-users", identity.api_accounts),
    path("api-users/<uuid:api_user_identifier>", identity.api_account_detail),
    path("api-users/<uuid:api_user_identifier>/role", identity.assign_role),
    path(
        "api-users/<uuid:api_user_identifier>/permissions",
        identity.individual_permissions,
    ),
    path(
        "api-users/<uuid:api_user_identifier>/credentials", identity.issue_credentials
    ),
    path("api-users/<uuid:api_user_identifier>/sympla-token", identity.provider_token),
    path("credentials/<uuid:credential_identifier>", identity.revoke_credentials),
    path("roles", identity.roles),
    path("roles/<uuid:role_identifier>", identity.role_detail),
    path("roles/<uuid:role_identifier>/permissions", identity.role_permissions),
    path("permissions", identity.permissions),
    path("access-rules", identity.access_rules),
    path("access-rules/<uuid:rule_identifier>", identity.remove_rule),
    path("api/users", identity.api_accounts),
    path("api/users/<uuid:api_user_identifier>", identity.api_account_detail),
    path("api/v1/api-users/", identity.api_accounts),
    path("api/v1/api-users/<uuid:api_user_identifier>/", identity.api_account_detail),
    path("api/v1/token/", token, name="api-token"),
    path("docs/", docs.swagger, name="swagger"),
    path("swagger/", docs.swagger),
    path("openapi.json", docs.schema, name="openapi-schema"),
    path("docs/assets/<str:filename>", docs.asset, name="swagger-asset"),
    path("ping/", views.ping),
    path("api/v1/schedules/", views.schedules),
    path("api/v1/schedules/<int:schedule_id>/", views.schedule_detail),
    path("api/v1/sync/", views.sync_now),
    path("api/v1/sync-runs/", views.runs),
    path("api/v1/sync-runs/<uuid:run_id>/", views.run_detail),
    path("api/v1/events/", views.events),
    path("api/v1/events/<int:event_id>/versions/", views.versions),
    path("api/v1/audit-logs/", views.audit_logs),
    path("api/v1/request-logs/", views.request_logs),
]
