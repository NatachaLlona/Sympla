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


class Integration(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(ApiUser, on_delete=models.PROTECT)
    name = models.CharField(max_length=80)
    provider = models.CharField(max_length=32)
    configuration = models.JSONField(default=dict)
    active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    revision = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(default=django_timezone.now)
    updated_at = models.DateTimeField(default=django_timezone.now)
    deleted_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['owner', 'name'], condition=Q(deleted_at__isnull=True), name='unique_live_integration_name'),
            models.UniqueConstraint(fields=['owner'], condition=Q(is_default=True, deleted_at__isnull=True), name='unique_default_integration'),
        ]


class Schedule(models.Model):
    integration = models.ForeignKey(Integration, on_delete=models.PROTECT)
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
                fields=["owner", "integration", "time", "timezone"],
                condition=Q(deleted_at__isnull=True),
                name="unique_live_schedule",
            )
        ]


class SyncRun(models.Model):
    integration = models.ForeignKey(Integration, on_delete=models.PROTECT)
    integration_revision = models.PositiveIntegerField(default=0)
    connector_version = models.CharField(max_length=80, blank=True)
    collected_at = models.DateTimeField(null=True)
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
                    Q(status="running", running_slot__in=[1, 2], running_slot__isnull=False)
                    | (~Q(status="running") & Q(running_slot__isnull=True))
                ),
                name="valid_running_slot",
            ),
        ]


class Event(models.Model):
    integration = models.ForeignKey(Integration, on_delete=models.PROTECT)
    name = models.TextField(blank=True)
    reference_id = models.TextField(blank=True)
    detail = models.TextField(blank=True)
    start_date = models.CharField(max_length=64, blank=True, db_index=True)
    end_date = models.CharField(max_length=64, blank=True)
    published = models.BooleanField(null=True)
    cancelled = models.BooleanField(null=True)
    private_event = models.BooleanField(null=True)
    url = models.TextField(blank=True)
    image = models.TextField(blank=True)
    first_seen_at = models.DateTimeField(null=True)
    last_seen_at = models.DateTimeField(null=True, db_index=True)
    last_run = models.ForeignKey(SyncRun, null=True, on_delete=models.PROTECT, related_name='last_seen_events')
    owner = models.ForeignKey(ApiUser, on_delete=models.PROTECT)
    external_id = models.CharField(max_length=200)
    version = models.PositiveIntegerField(default=0)
    fingerprint = models.CharField(max_length=64, blank=True)
    data = models.JSONField(default=dict)
    updated_at = models.DateTimeField(default=django_timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["integration", "external_id"], name="unique_integration_event"
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


class EventAddress(models.Model):
    event = models.OneToOneField(Event, on_delete=models.CASCADE, related_name='address')
    name = models.TextField(blank=True)
    address = models.TextField(blank=True)
    address_alt = models.TextField(blank=True)
    address_num = models.TextField(blank=True)
    neighborhood = models.TextField(blank=True)
    city = models.TextField(blank=True, db_index=True)
    state = models.TextField(blank=True)
    zip_code = models.TextField(blank=True)
    country = models.TextField(blank=True)
    lat = models.TextField(blank=True)
    lon = models.TextField(blank=True)


class EventHost(models.Model):
    event = models.OneToOneField(Event, on_delete=models.CASCADE, related_name='host')
    name = models.TextField(blank=True)
    description = models.TextField(blank=True)


class EventCategory(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='categories')
    kind = models.CharField(max_length=10, choices=[('primary', 'Primary'), ('secondary', 'Secondary')])
    name = models.TextField(blank=True, db_index=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['event', 'kind'], name='unique_event_category_kind')]


class EventObservation(models.Model):
    event = models.ForeignKey(Event, on_delete=models.PROTECT, related_name='observations')
    event_version = models.ForeignKey(EventVersion, on_delete=models.PROTECT)
    run = models.ForeignKey(SyncRun, on_delete=models.PROTECT)
    collected_at = models.DateTimeField()
    fingerprint = models.CharField(max_length=64)
    transformation_version = models.CharField(max_length=80)
    evidence_type = models.CharField(max_length=20, default='import')

    class Meta:
        constraints = [models.UniqueConstraint(fields=['event', 'run'], name='unique_event_run_observation')]


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


class Geography(models.Model):
    code = models.CharField(max_length=20)
    level = models.CharField(max_length=20, choices=[('state', 'State'), ('city', 'City'), ('neighborhood', 'Neighborhood'), ('district', 'District')])
    name = models.CharField(max_length=200)
    reference_year = models.PositiveSmallIntegerField(default=2022)
    parent = models.ForeignKey('self', null=True, on_delete=models.PROTECT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['code', 'level', 'reference_year'], name='unique_geography_reference')]


class GeographyMapReference(models.Model):
    geography = models.OneToOneField(Geography, on_delete=models.PROTECT, related_name='map_reference')
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True)
    area_km2 = models.DecimalField(max_digits=18, decimal_places=6, null=True)
    coordinate_kind = models.CharField(max_length=40, blank=True)
    reference_year = models.PositiveSmallIntegerField(default=2022)
    provenance = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(latitude__isnull=True, longitude__isnull=True) | models.Q(latitude__isnull=False, longitude__isnull=False, latitude__gte=-90, latitude__lte=90, longitude__gte=-180, longitude__lte=180), name='valid_map_coordinates'),
            models.CheckConstraint(condition=models.Q(area_km2__isnull=True) | models.Q(area_km2__gt=0), name='positive_map_area'),
        ]


class StatisticalIndicator(models.Model):
    code = models.CharField(max_length=80, primary_key=True)
    name = models.CharField(max_length=200)
    unit = models.CharField(max_length=40)
    universe = models.CharField(max_length=250)


class StatisticalCategory(models.Model):
    indicator = models.ForeignKey(StatisticalIndicator, on_delete=models.PROTECT)
    code = models.CharField(max_length=40)
    name = models.CharField(max_length=100)
    age_min = models.PositiveSmallIntegerField(null=True)
    age_max = models.PositiveSmallIntegerField(null=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['indicator', 'code'], name='unique_indicator_category')]


class Statistic(models.Model):
    integration = models.ForeignKey(Integration, on_delete=models.PROTECT)
    geography = models.ForeignKey(Geography, on_delete=models.PROTECT)
    category = models.ForeignKey(StatisticalCategory, on_delete=models.PROTECT)
    period = models.CharField(max_length=20, default='2022')
    value = models.DecimalField(max_digits=24, decimal_places=6, null=True)
    source_status = models.CharField(max_length=30, default='available')
    fingerprint = models.CharField(max_length=64)
    version = models.PositiveIntegerField(default=1)
    first_seen_at = models.DateTimeField(default=django_timezone.now)
    last_seen_at = models.DateTimeField(default=django_timezone.now)
    last_run = models.ForeignKey(SyncRun, on_delete=models.PROTECT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['integration', 'geography', 'category', 'period'], name='unique_statistic_series')]


class StatisticVersion(models.Model):
    statistic = models.ForeignKey(Statistic, on_delete=models.PROTECT)
    version = models.PositiveIntegerField()
    value = models.DecimalField(max_digits=24, decimal_places=6, null=True)
    source_status = models.CharField(max_length=30)
    fingerprint = models.CharField(max_length=64)
    run = models.ForeignKey(SyncRun, on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=django_timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['statistic', 'version'], name='unique_statistic_version')]


class ImportSource(models.Model):
    run = models.ForeignKey(SyncRun, on_delete=models.PROTECT)
    code = models.CharField(max_length=80)
    url = models.TextField()
    sha256 = models.CharField(max_length=64)
    reference_period = models.CharField(max_length=20)
    collected_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['run', 'code'], name='unique_run_source')]


class StatisticObservation(models.Model):
    statistic = models.ForeignKey(Statistic, on_delete=models.PROTECT)
    statistic_version = models.ForeignKey(StatisticVersion, on_delete=models.PROTECT)
    source = models.ForeignKey(ImportSource, on_delete=models.PROTECT)
    run = models.ForeignKey(SyncRun, on_delete=models.PROTECT)
    source_columns = models.CharField(max_length=200)
    transformation_version = models.CharField(max_length=80)
    collected_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['statistic', 'run'], name='unique_statistic_run_observation')]


class DataCoverage(models.Model):
    run = models.ForeignKey(SyncRun, on_delete=models.PROTECT)
    level = models.CharField(max_length=20)
    parent_code = models.CharField(max_length=20)
    status = models.CharField(max_length=30)
    record_count = models.PositiveIntegerField(default=0)
    message = models.CharField(max_length=250)
