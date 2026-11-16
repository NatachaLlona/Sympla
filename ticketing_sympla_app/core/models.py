from django.db import models
from django.db.models import Q
from django.utils import timezone as django_timezone
import uuid


class Coordinator(models.Model):
    """Singleton row for short queue/schedule transactions, never external HTTP calls."""

    pass


class Permission(models.Model):
    code = models.CharField(max_length=64, primary_key=True)
    description = models.CharField(max_length=100)


class Role(models.Model):
    identifier = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    name = models.CharField(max_length=80, unique=True)
    description = models.CharField(max_length=200, blank=True)
    is_system = models.BooleanField(default=False)
    permissions = models.ManyToManyField(Permission)


class ApiUser(models.Model):
    identifier = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    credential_identifier = models.UUIDField(
        default=uuid.uuid4, unique=True, editable=False
    )
    role = models.ForeignKey(Role, null=True, on_delete=models.PROTECT)
    is_superuser = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True)
    sympla_token_encrypted = models.TextField(blank=True)
    provider_version = models.PositiveIntegerField(default=1)
    client_id = models.CharField(max_length=100, unique=True, db_column="username")
    token_hash = models.CharField(max_length=64, unique=True, null=True)
    client_secret_hash = models.CharField(max_length=256, blank=True)
    credential_version = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    can_write = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=django_timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["is_superuser"],
                condition=Q(is_superuser=True),
                name="one_bootstrap_master",
            )
        ]


class AccessRule(models.Model):
    identifier = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    api_account = models.ForeignKey(
        ApiUser, on_delete=models.PROTECT, db_column="user_id"
    )
    permission = models.ForeignKey(Permission, on_delete=models.PROTECT)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["api_account", "permission"],
                name="unique_individual_permission",
            )
        ]


class AccessToken(models.Model):
    token_hash = models.CharField(max_length=64, unique=True)
    api_account = models.ForeignKey(
        ApiUser, on_delete=models.CASCADE, db_column="user_id"
    )
    credential_version = models.PositiveIntegerField()
    expires_at = models.DateTimeField(db_index=True)


class TokenThrottle(models.Model):
    key = models.CharField(max_length=64, unique=True)
    window_started = models.DateTimeField()
    attempts = models.PositiveIntegerField(default=0)


class Schedule(models.Model):
    owner = models.ForeignKey(ApiUser, on_delete=models.PROTECT)
    time = models.TimeField()
    timezone = models.CharField(max_length=100)
    active = models.BooleanField(default=True)
    next_run_at = models.DateTimeField(db_index=True)
    deleted_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(default=django_timezone.now)
    created_by = models.CharField(max_length=100)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "time", "timezone"],
                condition=Q(deleted_at__isnull=True),
                name="unique_live_schedule",
            )
        ]


class SyncRun(models.Model):
    owner = models.ForeignKey(ApiUser, on_delete=models.PROTECT)
    provider_version = models.PositiveIntegerField(default=0)
    id = models.UUIDField(primary_key=True)
    source = models.CharField(max_length=10)
    actor = models.CharField(max_length=100)
    schedule = models.ForeignKey(Schedule, null=True, on_delete=models.PROTECT)
    scheduled_for = models.DateTimeField(null=True)
    status = models.CharField(max_length=12, default="queued", db_index=True)
    created_at = models.DateTimeField(default=django_timezone.now)
    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)
    error_code = models.CharField(max_length=50, blank=True)
    error_details = models.JSONField(default=dict)
    counts = models.JSONField(default=dict)
    running_slot = models.PositiveSmallIntegerField(null=True, unique=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["schedule", "scheduled_for"], name="unique_schedule_occurrence"
            ),
            models.CheckConstraint(
                condition=(
                    Q(status="running", running_slot=1, running_slot__isnull=False)
                    | (~Q(status="running") & Q(running_slot__isnull=True))
                ),
                name="valid_running_slot",
            ),
        ]


class Event(models.Model):
    owner = models.ForeignKey(ApiUser, on_delete=models.PROTECT)
    external_id = models.CharField(max_length=200)
    version = models.PositiveIntegerField(default=0)
    fingerprint = models.CharField(max_length=64, blank=True)
    data = models.JSONField(default=dict)
    updated_at = models.DateTimeField(default=django_timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "external_id"], name="unique_owner_event"
            )
        ]


class EventVersion(models.Model):
    event = models.ForeignKey(Event, on_delete=models.PROTECT, related_name="versions")
    version = models.PositiveIntegerField()
    data = models.JSONField()
    differences = models.JSONField()
    run = models.ForeignKey(SyncRun, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=django_timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["event", "version"], name="unique_event_version"
            )
        ]


class AuditLog(models.Model):
    owner_identifier = models.UUIDField(null=True, db_index=True)
    interaction_id = models.UUIDField(db_index=True)
    created_at = models.DateTimeField(default=django_timezone.now, db_index=True)
    actor = models.CharField(max_length=100)
    action = models.CharField(max_length=50)
    resource = models.CharField(max_length=50)
    target_id = models.CharField(max_length=200)
    differences = models.JSONField(default=dict)
    outcome = models.CharField(max_length=20, default="committed")


class ApiRequestLog(models.Model):
    owner_identifier = models.UUIDField(null=True, db_index=True)
    interaction_id = models.UUIDField(unique=True)
    started_at = models.DateTimeField(default=django_timezone.now)
    finished_at = models.DateTimeField()
    actor = models.CharField(max_length=100, blank=True)
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=200)
    http_status = models.PositiveSmallIntegerField()
