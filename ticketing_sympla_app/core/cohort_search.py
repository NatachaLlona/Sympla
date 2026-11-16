"""Calendar-year cohort alignment; never presented as a current population forecast."""
from collections import defaultdict
from decimal import Decimal
from zoneinfo import ZoneInfo
from django.http import JsonResponse
from django.utils import timezone
from .auth import api_endpoint
from .api_errors import ApiProblem
from .identity import identifier
from .models import Statistic, Geography
from .integration_modules.ibge.catalog import AGE_BANDS

METHOD = 'calendar_year_cohort_shift_v1'
LIMITATIONS = [
    'This shifts the ages of people observed in the source census. It is not a current population forecast.',
    'Births after the census, deaths and migration are not modeled. Calendar-year alignment does not track individual birthdays.',
    'Partial age-band intersections produce bounds. Optional point estimates assume a uniform distribution within each closed source age band.',
    'Neighborhoods and districts are distinct official geography levels. Only data from an owned integration is searched.',
]


def current_year():
    return timezone.localdate(timezone=ZoneInfo('Europe/Lisbon')).year


def integer_parameter(request, name, default, minimum, maximum):
    try:
        raw = request.GET.get(name, str(default))
        if not raw.isascii() or not raw.isdigit():
            raise ValueError()
        value = int(raw)
        if not minimum <= value <= maximum:
            raise ValueError()
        return value
    except (ValueError, AttributeError):
        raise ApiProblem('invalid_search', f'{name} must be an integer between {minimum} and {maximum}.') from None


def available_statistics(api_account):
    return Statistic.objects.filter(integration__owner=api_account, category__indicator_id='age_population')


def parameters(request):
    allowed = {'integration_id', 'source_year', 'target_year', 'age_min', 'age_max', 'level',
               'state_code', 'city_code', 'sort', 'estimate', 'page', 'page_size'}
    if request.GET.keys() - allowed or any(len(values) != 1 for _, values in request.GET.lists()):
        raise ApiProblem('invalid_search', 'Use only the documented search parameters, once each.')
    source_year = integer_parameter(request, 'source_year', 2022, 2022, current_year())
    target_year = integer_parameter(request, 'target_year', current_year(), source_year, current_year())
    age_min = integer_parameter(request, 'age_min', target_year-source_year, 0, 130)
    age_max = integer_parameter(request, 'age_max', age_min+4, age_min, 130)
    estimate = request.GET.get('estimate', 'false')
    if estimate not in ('true', 'false'):
        raise ApiProblem('invalid_search', 'estimate must be true or false.')
    level = request.GET.get('level', 'district')
    if level not in ('state', 'city', 'neighborhood', 'district'):
        raise ApiProblem('invalid_search', 'Choose state, city, neighborhood or district.')
    sort = request.GET.get('sort', 'lower_bound')
    if sort not in ('lower_bound', 'upper_bound', 'estimate', 'share') or (sort == 'estimate' and estimate != 'true'):
        raise ApiProblem('invalid_search', 'Choose a documented sort; estimate sorting requires estimate=true.')
    scope = {}
    for name, length in [('state_code', 2), ('city_code', 7)]:
        code = request.GET.get(name, '')
        if code and (not code.isascii() or not code.isdigit() or len(code) != length):
            raise ApiProblem('invalid_search', f'{name} must be a {length}-digit IBGE code.')
        scope[name] = code
    if scope['state_code'] and scope['city_code'] and not scope['city_code'].startswith(scope['state_code']):
        raise ApiProblem('invalid_search', 'The municipality must belong to the selected state.')
    if scope['city_code'] and level == 'state':
        raise ApiProblem('invalid_search', 'A municipality filter cannot restrict state-level results.')
    return {'source_year': source_year, 'target_year': target_year, 'age_min': age_min, 'age_max': age_max,
            'estimate': estimate == 'true', 'level': level, 'sort': sort, **scope}


def count_value(row):
    if row is None or row.value is None or row.source_status != 'available' or row.value < 0 or row.value != row.value.to_integral_value():
        return None
    return int(row.value)


def align_cohort(rows, source_year, target_year, age_min, age_max, estimate=False):
    """Bound intersections without redistributing missing counts or post-census births."""
    advance = target_year-source_year
    source = {row.category.code: row for row in rows}
    lower, upper, point = 0, 0, Decimal(0)
    unknown, partial, contributions = [], False, []
    if age_min < advance:
        unknown.append('post_census_births')
    for code, label, minimum, maximum, _ in AGE_BANDS:
        shifted_min = minimum + advance
        shifted_max = maximum + advance if maximum is not None else None
        if shifted_min > age_max or (shifted_max is not None and shifted_max < age_min):
            continue
        row = source.get(code)
        value = count_value(row)
        entire = age_min <= shifted_min and shifted_max is not None and age_max >= shifted_max
        contribution = {'source_band': code, 'source_label': label, 'source_age_min': minimum,
            'source_age_max': maximum, 'aligned_age_min': shifted_min, 'aligned_age_max': shifted_max,
            'count': value, 'fully_included': entire, 'statistic_id': row.pk if row else None,
            'version': row.version if row else None, 'last_seen_at': row.last_seen_at if row else None,
            'last_run_id': row.last_run_id if row else None}
        contributions.append(contribution)
        if value is None:
            unknown.append('missing_or_suppressed_band')
            continue
        upper += value
        if entire:
            lower += value
            point += value
        else:
            partial = True
            if shifted_max is None:
                unknown.append('open_ended_band_estimate_unavailable')
            else:
                overlap = min(age_max, shifted_max)-max(age_min, shifted_min)+1
                point += Decimal(value)*Decimal(overlap)/Decimal(shifted_max-shifted_min+1)
    missing_count = any(flag in unknown for flag in ('post_census_births', 'missing_or_suppressed_band'))
    bounded_upper = None if missing_count else upper
    exact = not partial and not missing_count
    point_estimate = float(point.quantize(Decimal('0.01'))) if estimate and not unknown else None
    total = count_value(source.get('total'))
    share = round(lower/total*100, 4) if total else None
    upper_share = round(upper/total*100, 4) if total and bounded_upper is not None else None
    return {'lower_bound': lower, 'upper_bound': bounded_upper, 'exact_count': lower if exact else None,
        'estimated_count': point_estimate, 'match': 'exact_band_match' if exact else ('incomplete_coverage' if missing_count else 'bounded'),
        'source_age_total': total, 'lower_share_percent': share, 'upper_share_percent': upper_share,
        'flags': sorted(set(unknown)), 'bands': contributions,
        'estimate_method': 'uniform_within_closed_age_band' if point_estimate is not None and not exact else None}


@api_endpoint(['GET'], section='demographics')
def options(request):
    query = available_statistics(request.api_user)
    integrations = list(query.values('integration_id', 'integration__name').distinct().order_by('integration__name', 'integration_id'))
    source_years = sorted({int(value) for value in query.values_list('period', flat=True).distinct() if value.isascii() and value.isdigit()})
    return JsonResponse({'current_year': current_year(), 'source_years': source_years, 'integrations': [
        {'id': row['integration_id'], 'name': row['integration__name']} for row in integrations],
        'source_bands': [{'code': code, 'name': name, 'age_min': minimum, 'age_max': maximum} for code, name, minimum, maximum, _ in AGE_BANDS],
        'method': METHOD, 'limitations': LIMITATIONS})


@api_endpoint(['GET'], section='demographics')
def search(request):
    params = parameters(request)
    query = available_statistics(request.api_user).filter(period=str(params['source_year']))
    integration_id = request.GET.get('integration_id')
    if integration_id:
        integration_id = identifier(integration_id)
        query = query.filter(integration_id=integration_id)
    else:
        available = list(query.values_list('integration_id', flat=True).distinct()[:2])
        if len(available) > 1:
            raise ApiProblem('integration_required', 'Choose an integration_id to avoid combining duplicate sources.')
        integration_id = available[0] if available else None
    query = query.filter(geography__level=params['level'])
    if params['state_code']:
        query = query.filter(geography__code__startswith=params['state_code'])
    if params['city_code']:
        query = query.filter(geography__code=params['city_code']) if params['level'] == 'city' else query.filter(geography__parent__code=params['city_code'])
    rows = list(query.select_related('category', 'geography__parent').order_by('geography_id', 'category_id')[:100001])
    if len(rows) > 100000:
        raise ApiProblem('search_scope_limit', 'Narrow the search to a state or municipality.', 400)
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.geography_id].append(row)
    results = []
    for group in grouped.values():
        geography = group[0].geography
        aligned = align_cohort(group, params['source_year'], params['target_year'], params['age_min'], params['age_max'], params['estimate'])
        results.append({'geography': {'id': geography.pk, 'code': geography.code, 'name': geography.name,
            'level': geography.level, 'parent_code': geography.parent.code if geography.parent else None,
            'parent_name': geography.parent.name if geography.parent else None}, **aligned})
    key = {'lower_bound': 'lower_bound', 'upper_bound': 'upper_bound', 'estimate': 'estimated_count', 'share': 'lower_share_percent'}[params['sort']]
    results.sort(key=lambda row: (row[key] is None, -(row[key] or 0), row['geography']['name'], row['geography']['code']))
    previous, rank = object(), None
    for index, row in enumerate(results, 1):
        if row[key] is not None and row[key] != previous:
            rank = index
        row['rank'] = rank if row[key] is not None else None
        previous = row[key]
    page = integer_parameter(request, 'page', 1, 1, 100000)
    size = integer_parameter(request, 'page_size', 25, 1, 100)
    start = (page-1)*size
    response = {'count': len(results), 'page': page, 'page_size': size, 'integration_id': integration_id,
        'query': params, 'years_advanced': params['target_year']-params['source_year'], 'method': METHOD,
        'rank_basis': key, 'limitations': LIMITATIONS,
        'summary': {'exact_locations': sum(row['match'] == 'exact_band_match' for row in results),
            'bounded_locations': sum(row['match'] == 'bounded' for row in results),
            'incomplete_locations': sum(row['match'] == 'incomplete_coverage' for row in results)},
        'results': results[start:start+size]}
    if not results:
        response['empty_reason'] = 'No imported age data matches this scope. Official neighborhoods may be unavailable; districts are a separate level.'
    return JsonResponse(response)
