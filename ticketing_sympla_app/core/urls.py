from django.urls import path
from . import views
from . import docs
from .token_views import token

urlpatterns = [
    path('api/v1/token/', token, name='api-token'),
    path('docs/', docs.swagger, name='swagger'),
    path('swagger/', docs.swagger),
    path('openapi.json', docs.schema, name='openapi-schema'),
    path('docs/assets/<str:filename>', docs.asset, name='swagger-asset'),
    path('ping/', views.ping),
    path('api/v1/schedules/', views.schedules),
    path('api/v1/schedules/<int:schedule_id>/', views.schedule_detail),
    path('api/v1/sync/', views.sync_now),
    path('api/v1/sync-runs/', views.runs),
    path('api/v1/events/', views.events),
    path('api/v1/events/<int:event_id>/versions/', views.versions),
    path('api/v1/audit-logs/', views.audit_logs),
    path('api/v1/request-logs/', views.request_logs),
]
