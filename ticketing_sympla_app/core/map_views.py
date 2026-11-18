"""Owned demographic map: age cohorts, area income filters and event proximity."""
import copy
import math
from decimal import Decimal, InvalidOperation
from django.http import JsonResponse
from .api_errors import ApiProblem
from .auth import api_endpoint
from .cohort_search import search_data
from .models import Event, GeographyMapReference, Statistic
from .rbac import permitted

INCOME_METRICS = ('responsible_income_mean', 'responsible_income_median')
MAP_PARAMETERS = {'event_id', 'radius_km', 'income_min', 'income_max', 'income_metric', 'bbox', 'geography_code', 'venue_lat', 'venue_lon', 'max_travel_minutes'}


def amount(request, name, default=None, maximum=1000000000):
    raw = request.GET.get(name, '')
    if not raw:
        return default
    try:
        value = Decimal(raw)
        if not value.is_finite() or value < 0 or value > maximum:
            raise InvalidOperation()
        return value
    except InvalidOperation:
        raise ApiProblem('invalid_map_filter', f'{name} must be a finite nonnegative number up to {maximum}.') from None


def coordinates(latitude, longitude):
    try:
        lat, lon = float(latitude), float(longitude)
        if math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180:
            return lat, lon
    except (TypeError, ValueError):
        pass
    return None


def distance_km(first, second):
    lat1, lon1, lat2, lon2 = map(math.radians, (*first, *second))
    a = math.sin((lat2-lat1)/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 6371.0088*2*math.asin(min(1, math.sqrt(a)))


@api_endpoint(['GET'], section='demographics')
def map_data(request):
    for name in MAP_PARAMETERS:
        if len(request.GET.getlist(name)) > 1:
            raise ApiProblem('invalid_map_filter', 'Provide each map filter once.')
    minimum, maximum = amount(request, 'income_min'), amount(request, 'income_max')
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ApiProblem('invalid_map_filter', 'income_max must be greater than or equal to income_min.')
    metric = request.GET.get('income_metric', 'responsible_income_mean')
    if metric not in INCOME_METRICS:
        raise ApiProblem('invalid_map_filter', 'Choose responsible_income_mean or responsible_income_median.')
    radius = amount(request, 'radius_km', maximum=6000)
    travel_limit = amount(request, 'max_travel_minutes', maximum=1440)
    event, event_position = None, None
    if 'venue_lat' in request.GET or 'venue_lon' in request.GET:
        event_position = coordinates(request.GET.get('venue_lat'), request.GET.get('venue_lon'))
        if event_position is None:
            raise ApiProblem('invalid_venue', 'Provide a valid venue_lat and venue_lon pair.')
        event = {'id': None, 'name': 'Proposed venue', 'latitude': event_position[0], 'longitude': event_position[1], 'coordinate_status': 'available'}
    event_id = request.GET.get('event_id', '')
    if event_id:
        if event:
            raise ApiProblem('invalid_map_filter', 'Choose either an event or a proposed venue.')
        if not permitted(request.api_user, 'events:read'):
            return JsonResponse({'error': 'forbidden', 'required_permission': 'events:read'}, status=403)
        if not event_id.isascii() or not event_id.isdigit() or len(event_id) > 18:
            raise ApiProblem('invalid_map_filter', 'event_id must be an event database identifier.')
        record = Event.objects.select_related('address').filter(pk=int(event_id), owner=request.api_user).first()
        if not record:
            raise ApiProblem('not_found', 'Event not found.', 404)
        address = getattr(record, 'address', None)
        event_position = coordinates(address.lat, address.lon) if address else None
        event = {'id': record.pk, 'name': record.name, 'latitude': event_position[0] if event_position else None,
            'longitude': event_position[1] if event_position else None, 'coordinate_status': 'available' if event_position else 'not_available'}
        if radius is not None and event_position is None:
            raise ApiProblem('event_coordinates_missing', 'This event has no valid coordinates. Disable the distance filter or choose another event.')
    elif radius is not None and event is None:
        raise ApiProblem('invalid_map_filter', 'Choose an event before applying radius_km.')
    if travel_limit is not None and event_position is None:
        raise ApiProblem('invalid_map_filter', 'Choose an event or venue with coordinates before filtering travel time.')
    cohort_request = copy.copy(request)
    cohort_request.GET = request.GET.copy()
    for name in MAP_PARAMETERS:
        cohort_request.GET.pop(name, None)
    cohort_request.GET.setdefault('level', 'city')
    eligible = GeographyMapReference.objects.all()
    if request.GET.get('bbox'):
        try:
            west, south, east, north = map(float, request.GET['bbox'].split(','))
            if not all(math.isfinite(value) for value in (west,south,east,north)) or not -180 <= west < east <= 180 or not -90 <= south < north <= 90:
                raise ValueError()
        except (ValueError, TypeError):
            raise ApiProblem('invalid_bbox', 'bbox must be west,south,east,north in valid degrees.') from None
        eligible = eligible.filter(longitude__gte=west, longitude__lte=east, latitude__gte=south, latitude__lte=north)
    if request.GET.get('geography_code'):
        code = request.GET['geography_code']
        if not code.isascii() or not code.isdigit() or len(code) > 20:
            raise ApiProblem('invalid_map_filter', 'geography_code must be an official numeric code.')
        eligible = eligible.filter(geography__code=code)
    limited = request.GET.get('bbox') or request.GET.get('geography_code')
    if event_position and radius is not None:
        from django.db import connection
        if connection.vendor == 'postgresql':
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 FROM pg_extension WHERE extname='postgis'")
                spatial = cursor.fetchone()
            if spatial:
                eligible = eligible.filter(latitude__isnull=False, longitude__isnull=False).extra(
                    where=['ST_DWithin(ST_SetSRID(ST_MakePoint(longitude::double precision,latitude::double precision),4326)::geography, ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography,%s,false)'],
                    params=[event_position[1], event_position[0], float(radius)*1000+5])
                limited = True
    result = search_data(cohort_request, all_results=True, geography_ids=list(eligible.values_list('geography_id', flat=True)) if limited else None)
    if result['count'] > 3000:
        raise ApiProblem('map_scope_limit', 'Narrow the map to 3000 locations or fewer.')
    ids = [row['geography']['id'] for row in result['results']]
    references = {row.geography_id: row for row in GeographyMapReference.objects.filter(geography_id__in=ids)}
    income = {row.geography_id: row for row in Statistic.objects.filter(integration_id=result['integration_id'],
        geography_id__in=ids, period=str(result['query']['source_year']), category__indicator_id=metric, category__code='total')}
    points, missing_position, missing_area, missing_income, filtered_income, filtered_distance = [], 0, 0, 0, 0, 0
    for row in result['results']:
        code = row['geography']['id']
        observation = income.get(code)
        value = observation.value if observation and observation.source_status == 'available' else None
        if value is None:
            missing_income += 1
        if minimum is not None or maximum is not None:
            if value is None or (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
                filtered_income += 1
                continue
        reference = references.get(code)
        position = coordinates(reference.latitude, reference.longitude) if reference else None
        if position is None:
            missing_position += 1
            continue
        distance = distance_km(event_position, position) if event_position else None
        if radius is not None and distance > float(radius):
            filtered_distance += 1
            continue
        area = float(reference.area_km2) if reference.area_km2 else None
        if not area:
            missing_area += 1
        def density(count):
            return round(float(count)/area, 6) if count is not None and area else None
        points.append({**row, 'latitude': position[0], 'longitude': position[1], 'area_km2': area,
            'coordinate_kind': reference.coordinate_kind, 'spatial_reference_year': reference.reference_year,
            'spatial_provenance': reference.provenance, 'density_lower': density(row['lower_bound']),
            'density_upper': density(row['upper_bound']), 'density_estimate': density(row['estimated_count']),
            'income': {'metric': metric, 'value': str(value) if value is not None else None, 'unit': 'BRL_nominal_2022',
                'statistic_id': observation.pk if observation else None, 'version': observation.version if observation else None},
            'distance_km': round(distance, 2) if distance is not None else None})
    from .routing import travel_times, metadata
    routing = metadata()
    unroutable, excluded_time = 0, 0
    if travel_limit is not None:
        times, routing = travel_times(points,event_position)
        routed=[]
        for point in points:
            duration=times.get(point['geography']['code'])
            point['travel_minutes']=duration
            if duration is None:unroutable+=1
            elif duration>float(travel_limit):excluded_time+=1
            else:routed.append(point)
        points=routed
    return JsonResponse({'count': len(points), 'candidate_count': result['count'], 'integration_id': result['integration_id'],
        'routing': routing, 'max_travel_minutes': str(travel_limit) if travel_limit is not None else None,
        'query': result['query'], 'event': event, 'radius_km': str(radius) if radius is not None else None,
        'income_filter': {'metric': metric, 'minimum': str(minimum) if minimum is not None else None,
                         'maximum': str(maximum) if maximum is not None else None},
        'coverage': {'missing_coordinates': missing_position, 'missing_area': missing_area, 'missing_income': missing_income,
                     'excluded_by_income': filtered_income, 'excluded_by_distance': filtered_distance,
                     'unroutable_locations':unroutable,'excluded_by_travel_time':excluded_time},
        'method': result['method'], 'limitations': result['limitations']+[
            'Income filters select locality-level income summaries, not people in a joint age/income bracket.',
            'Bubbles are anchored at official administrative seats, not the residential location of every person.',
            'Density divides the aligned census cohort by the full official territorial area in km².',
            'Distance is straight-line distance between the event and the administrative seat, not travel time or intersection with the locality polygon.'],
        'results': points})
