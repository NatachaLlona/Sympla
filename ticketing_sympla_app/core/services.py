import hashlib
import json
import uuid
import logging
from django.db import transaction, IntegrityError
from django.utils import timezone
from .models import Schedule, SyncRun, Event, EventVersion, AuditLog, Coordinator
from .scheduling import next_occurrence
from .sympla import fetch_events, SyncError
from .sync_errors import message

logger = logging.getLogger(__name__)


def audit(actor, action, resource, target, differences=None, interaction=None, outcome='committed'):
    return AuditLog.objects.create(actor=actor, action=action, resource=resource,
        target_id=str(target), differences=differences or {},
        interaction_id=interaction or uuid.uuid4(), outcome=outcome)


def enqueue(actor, source='manual', schedule=None, scheduled_for=None, interaction=None):
    run = SyncRun.objects.create(id=uuid.uuid4(), source=source, actor=actor,
                                schedule=schedule, scheduled_for=scheduled_for)
    audit(actor, 'sync.queued', 'sync_run', run.pk, interaction=interaction)
    return run


@transaction.atomic
def enqueue_due(now=None):
    Coordinator.objects.select_for_update().get(pk=1)
    now = now or timezone.now()
    count = 0
    for schedule in Schedule.objects.select_for_update().filter(
            active=True, deleted_at__isnull=True, next_run_at__lte=now).order_by('id'):
        enqueue('scheduler', source='scheduled', schedule=schedule,
                scheduled_for=schedule.next_run_at)
        schedule.next_run_at = next_occurrence(schedule.time, schedule.timezone, now)
        schedule.save(update_fields=['next_run_at'])
        count += 1
    return count


def claim_run():
    try:
        with transaction.atomic():
            Coordinator.objects.select_for_update().get(pk=1)
            if SyncRun.objects.filter(status='running').exists():
                return None
            run = SyncRun.objects.select_for_update().filter(status='queued').order_by('created_at', 'id').first()
            if not run:
                return None
            run.status, run.running_slot, run.started_at = 'running', 1, timezone.now()
            run.save(update_fields=['status', 'running_slot', 'started_at'])
            audit(run.actor, 'sync.started', 'sync_run', run.pk, interaction=run.pk)
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
                child = path + '/' + key.replace('~', '~0').replace('/', '~1')
                if key not in old or key not in new:
                    changes[child] = {'before': old.get(key), 'after': new.get(key),
                                      'before_exists': key in old, 'after_exists': key in new}
                else:
                    visit(old[key], new[key], child)
        elif old != new or type(old) is not type(new):
            changes[path] = {'before': old, 'after': new, 'before_exists': True, 'after_exists': True}
    visit(before, after, '')
    return changes


EVENT_FIELDS = {'id', 'reference_id', 'name', 'detail', 'start_date', 'end_date', 'published',
                'cancelled', 'private_event', 'url', 'image'}
NESTED_FIELDS = {'address': {'name', 'address', 'address_alt', 'address_num', 'neighborhood',
                'city', 'state', 'zip_code', 'country', 'lat', 'lon'},
                'host': {'name', 'description'}, 'category_prim': {'name'}, 'category_sec': {'name'}}


def normalize(payload):
    # Persist only documented event fields; arbitrary upstream credential fields are excluded.
    result = {key: value for key, value in payload.items() if key in EVENT_FIELDS}
    if any(isinstance(value, (dict, list)) for value in result.values()):
        raise SyncError('upstream_invalid_event')
    for key, allowed in NESTED_FIELDS.items():
        if key in payload:
            nested = payload[key]
            if nested is not None and not isinstance(nested, dict):
                raise SyncError('upstream_invalid_event')
            result[key] = None if nested is None else {k: v for k, v in nested.items() if k in allowed}
            if nested and any(isinstance(v, (dict, list)) for k, v in nested.items() if k in allowed):
                raise SyncError('upstream_invalid_event')
    result['id'] = str(result['id'])
    return result


@transaction.atomic
def persist_events(run_id, payloads):
    run = SyncRun.objects.select_for_update().get(pk=run_id, status='running')
    counts = {'received': len(payloads), 'created': 0, 'updated': 0, 'unchanged': 0}
    for payload in payloads:
        data = normalize(payload)
        digest = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':'),
                                         allow_nan=False).encode()).hexdigest()
        event, created = Event.objects.get_or_create(external_id=data['id'])
        if event.fingerprint == digest:
            counts['unchanged'] += 1
            continue
        changes = differences(event.data, data)
        event.version += 1
        event.data, event.fingerprint, event.updated_at = data, digest, timezone.now()
        event.save()
        EventVersion.objects.create(event=event, version=event.version, data=data,
                                    differences=changes, run=run)
        audit(run.actor, 'event.created' if created else 'event.updated', 'event', event.external_id,
              changes, interaction=run.pk)
        counts['created' if created else 'updated'] += 1
    run.status, run.running_slot = 'success', None
    run.finished_at, run.counts = timezone.now(), counts
    run.save()
    audit(run.actor, 'sync.succeeded', 'sync_run', run.pk, counts, interaction=run.pk)
    return counts


def process_one():
    run = claim_run()
    if run is None:
        return None
    try:
        payloads = fetch_events()
        persist_events(run.pk, payloads)
    except Exception as exc:
        code = str(exc) if isinstance(exc, SyncError) else 'sync_internal_error'
        with transaction.atomic():
            current = SyncRun.objects.select_for_update().get(pk=run.pk)
            current.status, current.running_slot = 'failed', None
            current.finished_at, current.error_code = timezone.now(), code
            current.error_details = {'message': message(code), **(exc.details if isinstance(exc, SyncError) else {})}
            current.save()
            audit(current.actor, 'sync.failed', 'sync_run', run.pk,
                  {'error_code': code, **current.error_details}, interaction=run.pk, outcome='rolled_back')
        logger.error('Synchronization failed: run_id=%s error_code=%s details=%s',
                     run.pk, code, current.error_details)
    return SyncRun.objects.get(pk=run.pk)
