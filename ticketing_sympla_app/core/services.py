import hashlib
import json
import uuid
import logging
from django.db import transaction, IntegrityError
from django.utils import timezone
from .models import (
    Schedule,
    SyncRun,
    Event,
    EventVersion,
    AuditLog,
    Coordinator,
    ApiUser,
    Integration,
    EventObservation,
)
from .scheduling import next_occurrence
from .sympla import SyncError
from .connectors import connector_for
from .event_mapping import project
from .sync_errors import message
from .rbac import permitted
from .provider_secrets import ProviderSecretError

logger = logging.getLogger(__name__)


def audit(
    actor,
    action,
    resource,
    target,
    differences=None,
    interaction=None,
    outcome="committed",
    owner=None,
):
    return AuditLog.objects.create(
        actor=actor,
        action=action,
        resource=resource,
        owner_identifier=owner.identifier if owner else None,
        target_id=str(target),
        differences=differences or {},
        interaction_id=interaction or uuid.uuid4(),
        outcome=outcome,
    )


def enqueue(
    actor,
    source="manual",
    schedule=None,
    scheduled_for=None,
    interaction=None,
    owner=None,
    integration=None,
):
    owner = owner or (schedule.owner if schedule else None)
    if owner is None:
        raise ValueError("An explicit owner is required for synchronization.")
    if schedule is not None and schedule.owner_id != owner.pk:
        raise ValueError("A scheduled synchronization must use its schedule owner.")
    from .integrations import select_integration
    integration = integration or (schedule.integration if schedule else None) or select_integration(owner)
    if integration.owner_id != owner.pk or not integration.active or integration.deleted_at:
        raise ValueError('An active integration belonging to the synchronization owner is required.')
    if schedule is not None and schedule.integration_id != integration.pk:
        raise ValueError('The synchronization must use its schedule integration.')
    run = SyncRun.objects.create(
        id=uuid.uuid4(),
        source=source,
        actor=actor,
        owner=owner,
        integration=integration,
        schedule=schedule,
        scheduled_for=scheduled_for,
    )
    audit(
        actor, "sync.queued", "sync_run", run.pk, interaction=interaction, owner=owner
    )
    return run


@transaction.atomic
def enqueue_due(now=None, provider=None):
    Coordinator.objects.select_for_update().get(pk=1)
    now = now or timezone.now()
    count = 0
    for schedule in (
        Schedule.objects.select_for_update()
        .filter(
            active=True,
            deleted_at__isnull=True,
            owner__is_active=True,
            owner__deleted_at__isnull=True,
            integration__active=True,
            integration__deleted_at__isnull=True,
            next_run_at__lte=now,
        )
        .order_by("id")
    ):
        if provider and schedule.integration.provider != provider:
            continue
        if not permitted(schedule.owner, "synchronization:write"):
            continue
        enqueue(
            "scheduler",
            source="scheduled",
            schedule=schedule,
            scheduled_for=schedule.next_run_at,
        )
        schedule.next_run_at = next_occurrence(schedule.time, schedule.timezone, now)
        schedule.save(update_fields=["next_run_at"])
        count += 1
    return count


def claim_run(provider=None):
    try:
        with transaction.atomic():
            Coordinator.objects.select_for_update().get(pk=1)
            run = (
                SyncRun.objects.select_for_update()
                .filter(status="queued", **({"integration__provider": provider} if provider else {}))
                .order_by("created_at", "id")
                .first()
            )
            if not run:
                return None
            connector = connector_for(run.integration.provider)
            slot = getattr(connector, 'running_slot', 1)
            if SyncRun.objects.filter(status='running', running_slot=slot).exists():
                return None
            owner = ApiUser.objects.select_for_update().get(pk=run.owner_id)
            if not permitted(owner, "synchronization:write") or run.integration.owner_id != owner.pk or not run.integration.active or run.integration.deleted_at:
                run.status, run.finished_at, run.error_code = (
                    "cancelled",
                    timezone.now(),
                    "owner_not_authorized",
                )
                run.save()
                audit(
                    owner.client_id,
                    "sync.cancelled",
                    "sync_run",
                    run.pk,
                    interaction=run.pk,
                    owner=owner,
                )
                return None
            run.provider_version = owner.provider_version if connector.credential_scope == 'api_account' else 0
            run.integration_revision = run.integration.revision
            run.connector_version = connector_for(run.integration.provider).version
            run.status, run.running_slot, run.started_at = "running", slot, timezone.now()
            run.save(
                update_fields=[
                    "status",
                    "running_slot",
                    "started_at",
                    "provider_version",
                    "integration_revision",
                    "connector_version",
                ]
            )
            audit(
                run.actor,
                "sync.started",
                "sync_run",
                run.pk,
                interaction=run.pk,
                owner=owner,
            )
            return run
    except IntegrityError:
        # Another worker owns the global running slot.
        return None


def differences(before, after):
    """Field paths plus existence flags distinguish removal from JSON null."""
    changes = {}

    def visit(old, new, path):
        if isinstance(old, dict) and isinstance(new, dict):
            for key in sorted(old.keys() | new.keys()):
                child = path + "/" + key.replace("~", "~0").replace("/", "~1")
                if key not in old or key not in new:
                    changes[child] = {
                        "before": old.get(key),
                        "after": new.get(key),
                        "before_exists": key in old,
                        "after_exists": key in new,
                    }
                else:
                    visit(old[key], new[key], child)
        elif old != new or type(old) is not type(new):
            changes[path] = {
                "before": old,
                "after": new,
                "before_exists": True,
                "after_exists": True,
            }

    visit(before, after, "")
    return changes


@transaction.atomic
def persist_events(run_id, payloads):
    Coordinator.objects.select_for_update().get(pk=1)
    run = SyncRun.objects.select_for_update().get(pk=run_id, status="running")
    owner = ApiUser.objects.select_for_update().get(pk=run.owner_id)
    if not permitted(owner, "synchronization:write") or owner.provider_version != run.provider_version:
        raise SyncError("owner_authorization_changed")
    integration = Integration.objects.select_for_update().get(pk=run.integration_id)
    if integration.owner_id != owner.pk or not integration.active or integration.deleted_at or integration.revision != run.integration_revision:
        raise SyncError('integration_changed')
    connector = connector_for(integration.provider)
    if connector.version != run.connector_version:
        raise SyncError('integration_changed')
    collected_at = timezone.now()
    seen = set()
    counts = {"received": len(payloads), "created": 0, "updated": 0, "unchanged": 0}
    for payload in payloads:
        data = connector.normalize(payload)
        if data['id'] in seen:
            raise SyncError('upstream_duplicate_event')
        seen.add(data['id'])
        digest = hashlib.sha256(
            json.dumps(
                data, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        ).hexdigest()
        event, created = Event.objects.get_or_create(
            owner=owner, integration=integration, external_id=data["id"]
        )
        event.first_seen_at = event.first_seen_at or collected_at
        event.last_seen_at, event.last_run = collected_at, run
        if event.fingerprint == digest:
            event.save(update_fields=['first_seen_at', 'last_seen_at', 'last_run'])
            event_version = EventVersion.objects.get(event=event, version=event.version)
            EventObservation.objects.create(event=event, event_version=event_version, run=run, collected_at=collected_at, fingerprint=digest, transformation_version=connector.version)
            counts["unchanged"] += 1
            continue
        changes = differences(event.data, data)
        event.version += 1
        event.data, event.fingerprint, event.updated_at = data, digest, timezone.now()
        project(event, data)
        event_version = EventVersion.objects.create(
            event=event, version=event.version, data=data, differences=changes, run=run
        )
        EventObservation.objects.create(event=event, event_version=event_version, run=run, collected_at=collected_at, fingerprint=digest, transformation_version=connector.version)
        audit(
            run.actor,
            "event.created" if created else "event.updated",
            "event",
            event.pk,
            {'integration_id': str(integration.pk), 'external_id': event.external_id, 'fields': changes},
            interaction=run.pk,
            owner=owner,
        )
        counts["created" if created else "updated"] += 1
    run.status, run.running_slot = "success", None
    run.finished_at, run.counts, run.collected_at = timezone.now(), counts, collected_at
    run.save()
    audit(
        run.actor,
        "sync.succeeded",
        "sync_run",
        run.pk,
        counts,
        interaction=run.pk,
        owner=owner,
    )
    return counts


def process_one(provider=None):
    run = claim_run(provider)
    if run is None:
        return None
    try:
        owner = ApiUser.objects.get(pk=run.owner_id)
        payloads = connector_for(run.integration.provider).collect(run.integration, owner)
        if getattr(connector_for(run.integration.provider), 'domain', 'events') == 'statistics':
            from .statistics_services import persist_statistics
            persist_statistics(run.pk, payloads)
        else:
            persist_events(run.pk, payloads)
    except Exception as exc:
        code = (
            str(exc)
            if isinstance(exc, SyncError)
            else (
                "provider_secret_unavailable"
                if isinstance(exc, ProviderSecretError)
                else "sync_internal_error"
            )
        )
        with transaction.atomic():
            current = SyncRun.objects.select_for_update().get(pk=run.pk)
            current.status, current.running_slot = "failed", None
            current.finished_at, current.error_code = timezone.now(), code
            current.error_details = {
                "message": message(code),
                **(exc.details if isinstance(exc, SyncError) else {}),
            }
            current.save()
            audit(
                current.actor,
                "sync.failed",
                "sync_run",
                run.pk,
                {"error_code": code, **current.error_details},
                interaction=run.pk,
                outcome="rolled_back",
                owner=current.owner,
            )
        logger.error(
            "Synchronization failed: run_id=%s error_code=%s details=%s",
            run.pk,
            code,
            current.error_details,
        )
    return SyncRun.objects.get(pk=run.pk)
