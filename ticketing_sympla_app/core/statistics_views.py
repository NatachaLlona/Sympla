"""Read-only, owner-scoped demographics, geography and provenance APIs."""
from django.db.models import Q
from .auth import api_endpoint
from .identity import collection, identifier
from .api_errors import ApiProblem
from .models import Geography, Statistic, StatisticVersion, StatisticObservation, DataCoverage


def owned_statistics(request):
    query = Statistic.objects.filter(integration__owner=request.api_user).select_related('geography__parent', 'category__indicator', 'integration', 'last_run')
    for parameter, field in [('integration_id', 'integration_id'), ('level', 'geography__level'), ('code', 'geography__code'),
                             ('indicator', 'category__indicator_id'), ('category', 'category__code'), ('period', 'period')]:
        if parameter in request.GET:
            value = identifier(request.GET[parameter]) if parameter == 'integration_id' else request.GET[parameter]
            query = query.filter(**{field: value})
    return query.order_by('id')


def statistic_data(row):
    return {'id': row.pk, 'integration_id': row.integration_id, 'geography': {
        'id': row.geography_id, 'code': row.geography.code, 'name': row.geography.name,
        'level': row.geography.level, 'parent_code': row.geography.parent.code if row.geography.parent else None,
        'reference_year': row.geography.reference_year,
    }, 'indicator': row.category.indicator_id, 'indicator_name': row.category.indicator.name,
        'unit': row.category.indicator.unit, 'universe': row.category.indicator.universe,
        'category': row.category.code, 'category_name': row.category.name,
        'age_min': row.category.age_min, 'age_max': row.category.age_max, 'period': row.period,
        'value': int(row.value) if row.value is not None and row.category.indicator.unit == 'persons' else row.value,
        'source_status': row.source_status, 'version': row.version,
        'first_seen_at': row.first_seen_at, 'last_seen_at': row.last_seen_at, 'last_run_id': row.last_run_id}


@api_endpoint(['GET'], section='demographics')
def statistics(request):
    return collection(request, owned_statistics(request), statistic_data)


@api_endpoint(['GET'], section='demographics')
def geographies(request):
    owned = Statistic.objects.filter(integration__owner=request.api_user)
    query = Geography.objects.filter(Q(pk__in=owned.values('geography_id')) |
        Q(pk__in=owned.values('geography__parent_id')) | Q(pk__in=owned.values('geography__parent__parent_id'))).select_related('parent')
    for field in ('level', 'code'):
        if field in request.GET:
            query = query.filter(**{field: request.GET[field]})
    if 'parent_code' in request.GET:
        query = query.filter(parent__code=request.GET['parent_code'])
    return collection(request, query.order_by('level', 'code'), lambda row: {
        'id': row.pk, 'code': row.code, 'name': row.name, 'level': row.level,
        'reference_year': row.reference_year, 'parent_code': row.parent.code if row.parent else None})


def target_statistic(request, statistic_id):
    if not Statistic.objects.filter(pk=statistic_id, integration__owner=request.api_user).exists():
        raise ApiProblem('not_found', 'Statistic not found.', 404)


@api_endpoint(['GET'], section='demographics')
def versions(request, statistic_id):
    target_statistic(request, statistic_id)
    return collection(request, StatisticVersion.objects.filter(statistic_id=statistic_id).order_by('-version'), lambda row: {
        'id': row.pk, 'version': row.version, 'value': row.value, 'source_status': row.source_status,
        'fingerprint': row.fingerprint, 'run_id': row.run_id, 'created_at': row.created_at})


@api_endpoint(['GET'], section='demographics')
def observations(request, statistic_id):
    target_statistic(request, statistic_id)
    return collection(request, StatisticObservation.objects.filter(statistic_id=statistic_id).select_related('source', 'statistic_version').order_by('-collected_at', '-id'), lambda row: {
        'id': row.pk, 'version': row.statistic_version.version, 'run_id': row.run_id, 'collected_at': row.collected_at,
        'source_url': row.source.url, 'source_sha256': row.source.sha256, 'source_columns': row.source_columns,
        'reference_period': row.source.reference_period, 'transformation_version': row.transformation_version})


@api_endpoint(['GET'], section='demographics')
def coverage(request):
    query = DataCoverage.objects.filter(run__owner=request.api_user).order_by('-id')
    if 'run_id' in request.GET:
        query = query.filter(run_id=identifier(request.GET['run_id']))
    return collection(request, query, lambda row: {field: getattr(row, field) for field in
        ('id', 'run_id', 'level', 'parent_code', 'status', 'record_count', 'message')})
