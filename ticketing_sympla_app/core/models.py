from django.db import models
from django.db.models import Q
from django.utils import timezone as django_timezone


class Coordinator(models.Model):
    """Singleton row for short queue/schedule transactions, never external HTTP calls."""
    pass


class ApiUser(models.Model):
    username = models.CharField(max_length=100, unique=True)
    token_hash = models.CharField(max_length=64, unique=True)
    is_active = models.BooleanField(default=True)
    can_write = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=django_timezone.now)


class Schedule(models.Model):
    time = models.TimeField()
    timezone = models.CharField(max_length=100)
    active = models.BooleanField(default=True)
    next_run_at = models.DateTimeField(db_index=True)
    deleted_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(default=django_timezone.now)
    created_by = models.CharField(max_length=100)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['time', 'timezone'],
                       condition=Q(deleted_at__isnull=True), name='unique_live_schedule')]


class SyncRun(models.Model):
    id = models.UUIDField(primary_key=True)
    source = models.CharField(max_length=10)
    actor = models.CharField(max_length=100)
    schedule = models.ForeignKey(Schedule, null=True, on_delete=models.PROTECT)
    scheduled_for = models.DateTimeField(null=True)
    status = models.CharField(max_length=12, default='queued', db_index=True)
    created_at = models.DateTimeField(default=django_timezone.now)
    started_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)
    error_code = models.CharField(max_length=50, blank=True)
    counts = models.JSONField(default=dict)
    running_slot = models.PositiveSmallIntegerField(null=True, unique=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['schedule', 'scheduled_for'], name='unique_schedule_occurrence'),
            models.CheckConstraint(condition=(Q(status='running', running_slot=1, running_slot__isnull=False) |
                (~Q(status='running') & Q(running_slot__isnull=True))), name='valid_running_slot'),
        ]


class Event(models.Model):
    external_id = models.CharField(max_length=200, unique=True)
    version = models.PositiveIntegerField(default=0)
    fingerprint = models.CharField(max_length=64, blank=True)
    data = models.JSONField(default=dict)
    updated_at = models.DateTimeField(default=django_timezone.now)


class EventVersion(models.Model):
    event = models.ForeignKey(Event, on_delete=models.PROTECT, related_name='versions')
    version = models.PositiveIntegerField()
    data = models.JSONField()
    differences = models.JSONField()
    run = models.ForeignKey(SyncRun, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=django_timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['event', 'version'], name='unique_event_version')]


class AuditLog(models.Model):
    interaction_id = models.UUIDField(db_index=True)
    created_at = models.DateTimeField(default=django_timezone.now, db_index=True)
    actor = models.CharField(max_length=100)
    action = models.CharField(max_length=50)
    resource = models.CharField(max_length=50)
    target_id = models.CharField(max_length=200)
    differences = models.JSONField(default=dict)
    outcome = models.CharField(max_length=20, default='committed')


class ApiRequestLog(models.Model):
    interaction_id = models.UUIDField(unique=True)
    started_at = models.DateTimeField(default=django_timezone.now)
    finished_at = models.DateTimeField()
    actor = models.CharField(max_length=100, blank=True)
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=200)
    http_status = models.PositiveSmallIntegerField()
