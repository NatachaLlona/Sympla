"""Relational event reads and immutable import lineage."""
from django.http import JsonResponse
from .api_errors import ApiProblem
from .auth import api_endpoint
from .models import Event, EventObservation
from .identity import collection, identifier


def event_query(api_account):
    return Event.objects.filter(owner=api_account).select_related('integration', 'address', 'host').prefetch_related('categories').order_by('id')


def related_data(item, fields):
    return {field: getattr(item, field) for field in fields} if item else None


def event_data(event):
    result = {field: getattr(event, field) for field in (
        'id', 'external_id', 'integration_id', 'version', 'updated_at', 'name', 'reference_id', 'detail',
        'start_date', 'end_date', 'published', 'cancelled', 'private_event', 'url', 'image',
        'first_seen_at', 'last_seen_at', 'last_run_id', 'data',
    )}
    result['provider'] = event.integration.provider
    result['address'] = related_data(getattr(event, 'address', None), (
        'name', 'address', 'address_alt', 'address_num', 'neighborhood', 'city', 'state', 'zip_code', 'country', 'lat', 'lon',
    ))
    result['host'] = related_data(getattr(event, 'host', None), ('name', 'description'))
    result['categories'] = [{'kind': row.kind, 'name': row.name} for row in event.categories.all()]
    return result


def filtered_events(request):
    query = event_query(request.api_user)
    if 'integration_id' in request.GET:
        query = query.filter(integration_id=identifier(request.GET['integration_id']))
    if 'city' in request.GET:
        query = query.filter(address__city=request.GET['city'])
    return query


@api_endpoint(['GET'], section='events')
def event_detail(request, event_id):
    event = event_query(request.api_user).filter(pk=event_id).first()
    if not event:
        raise ApiProblem('not_found', 'Event not found.', 404)
    return JsonResponse(event_data(event))


@api_endpoint(['GET'], section='events')
def observations(request, event_id):
    if not Event.objects.filter(pk=event_id, owner=request.api_user).exists():
        raise ApiProblem('not_found', 'Event not found.', 404)
    query = EventObservation.objects.filter(event_id=event_id).select_related('run__integration', 'event_version', 'event').order_by('-collected_at', '-id')
    return collection(request, query, lambda row: {
        'id': row.pk, 'event_id': row.event_id, 'event_version': row.event_version.version,
        'run_id': row.run_id, 'integration_id': row.run.integration_id,
        'provider': row.run.integration.provider, 'external_id': row.event.external_id,
        'source': row.run.source, 'actor': row.run.actor, 'collected_at': row.collected_at,
        'fingerprint': row.fingerprint, 'transformation_version': row.transformation_version,
        'evidence_type': row.evidence_type,
    })
