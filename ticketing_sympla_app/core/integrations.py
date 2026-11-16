"""Owner-scoped integration configuration; credentials remain API-account scoped."""
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from .auth import api_endpoint
from .api_errors import ApiProblem
from .models import Integration, Schedule, SyncRun
from .identity import payload, collection, identifier
from .connectors import CONNECTORS
from .services import audit


def default_integration(api_account):
    integration = Integration.objects.filter(owner=api_account, is_default=True, deleted_at__isnull=True).first()
    if not integration:
        raise ApiProblem('integration_required', 'Choose an integration identifier or configure a default integration.', 409)
    return integration


def select_integration(api_account, value=None):
    integration = default_integration(api_account) if value is None else Integration.objects.filter(
        owner=api_account, pk=identifier(value), deleted_at__isnull=True,
    ).first()
    if not integration:
        raise ApiProblem('not_found', 'Integration not found.', 404)
    if not integration.active:
        raise ApiProblem('integration_inactive', 'The integration is inactive.', 409)
    return integration


def integration_data(integration):
    return {key: getattr(integration, key) for key in (
        'id', 'name', 'provider', 'active', 'is_default', 'revision', 'created_at', 'updated_at'
    )}


def validate(data):
    if 'name' in data and (not isinstance(data['name'], str) or not 1 <= len(data['name']) <= 80 or not data['name'].strip() or not data['name'].isprintable()):
        raise ApiProblem('invalid_name', 'Use a printable integration name containing 1 to 80 characters.')
    if 'provider' in data and (not isinstance(data['provider'], str) or data['provider'] not in CONNECTORS):
        raise ApiProblem('unsupported_integration', 'Choose a registered connector from GET /api/v1/integration-providers/.')
    for field in ('active', 'is_default'):
        if field in data and type(data[field]) is not bool:
            raise ApiProblem('invalid_request', f'{field} must be a boolean.')


def record(request, integration, action, changes):
    audit(request.api_user.client_id, action, 'integration', integration.pk,
          changes, request.interaction_id, owner=request.api_user)


def cancel_pending(request, integration):
    for run in SyncRun.objects.select_for_update().filter(integration=integration, status='queued'):
        run.status, run.finished_at, run.error_code = 'cancelled', timezone.now(), 'integration_unavailable'
        run.save(update_fields=['status', 'finished_at', 'error_code'])
        audit(request.api_user.client_id, 'sync.cancelled', 'sync_run', run.pk,
              interaction=request.interaction_id, owner=request.api_user)


def clear_previous_default(request, selected_id=None):
    for previous in Integration.objects.select_for_update().filter(
        owner=request.api_user, is_default=True, deleted_at__isnull=True,
    ).exclude(pk=selected_id):
        previous.is_default = False
        previous.updated_at = timezone.now()
        previous.save(update_fields=['is_default', 'updated_at'])
        record(request, previous, 'integration.updated', {'is_default': {'before': True, 'after': False}})


@api_endpoint(['GET'], section='integrations')
def providers(request):
    return JsonResponse({'results': [{'code': item.code, 'connector_version': item.version,
                                     'credential_scope': item.credential_scope} for item in CONNECTORS.values()]})


@api_endpoint(['GET', 'POST'], section='integrations')
def integrations(request):
    if request.method == 'GET':
        return collection(request, Integration.objects.filter(owner=request.api_user, deleted_at__isnull=True).order_by('created_at', 'id'), integration_data)
    data = payload(request, ['name', 'provider', 'active', 'is_default'], ['name', 'provider'])
    validate(data)
    if Integration.objects.filter(owner=request.api_user, deleted_at__isnull=True).count() >= 100:
        raise ApiProblem('integration_limit', 'A maximum of 100 live integrations is allowed per API account.', 409)
    if data.get('is_default'):
        clear_previous_default(request)
    integration = Integration.objects.create(owner=request.api_user, **data)
    record(request, integration, 'integration.created', data)
    return JsonResponse(integration_data(integration), status=201)


@api_endpoint(['GET', 'PATCH', 'DELETE'], section='integrations')
def integration_detail(request, integration_id):
    integration = Integration.objects.select_for_update().filter(owner=request.api_user, pk=integration_id, deleted_at__isnull=True).first()
    if not integration:
        raise ApiProblem('not_found', 'Integration not found.', 404)
    if request.method == 'GET':
        return JsonResponse(integration_data(integration))
    if request.method == 'DELETE':
        changes = {'active': False, 'deleted': True}
        integration.active, integration.deleted_at = False, timezone.now()
        for schedule in Schedule.objects.filter(integration=integration, deleted_at__isnull=True, active=True):
            schedule.active = False
            schedule.save(update_fields=['active'])
            audit(request.api_user.client_id, 'schedule.updated', 'schedule', schedule.pk,
                  {'active': {'before': True, 'after': False}, 'reason': 'integration_deleted'}, request.interaction_id, owner=request.api_user)
    else:
        changes = payload(request, ['name', 'active', 'is_default'])
        if not changes:
            raise ApiProblem('invalid_request', 'Provide at least one integration field.')
        validate(changes)
        if changes.get('is_default'):
            clear_previous_default(request, integration.pk)
        for key, value in changes.items():
            setattr(integration, key, value)
    integration.revision += 1
    integration.updated_at = timezone.now()
    integration.save()
    if not integration.active:
        cancel_pending(request, integration)
    record(request, integration, 'integration.deleted' if request.method == 'DELETE' else 'integration.updated', changes)
    return HttpResponse(status=204) if request.method == 'DELETE' else JsonResponse(integration_data(integration))
