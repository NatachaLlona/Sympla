"""Swagger contract for the demographic map and its locality-level income filter."""
import copy


def extend(schema):
    from .openapi import obj, text, integer, ref, operation
    number = {'type': 'number', 'nullable': True}
    schemas = schema['components']['schemas']
    schemas['MapLocation'] = {'allOf': [ref('CohortLocation'), obj({
        'latitude': {'type': 'number'}, 'longitude': {'type': 'number'}, 'area_km2': number,
        'coordinate_kind': text(), 'spatial_reference_year': integer(), 'spatial_provenance': {'type': 'object'},
        'density_lower': number, 'density_upper': number, 'density_estimate': number, 'distance_km': number,
        'income': obj({'metric': text(), 'value': text(nullable=True), 'unit': text(), 'statistic_id': integer(nullable=True), 'version': integer(nullable=True)})})]}
    schemas['DemographicMap'] = obj({'count': integer(), 'candidate_count': integer(), 'integration_id': text(format='uuid', nullable=True),
        'query': {'type': 'object'}, 'event': {'type': 'object', 'nullable': True}, 'radius_km': text(nullable=True),
        'income_filter': {'type': 'object'}, 'coverage': {'type': 'object'}, 'method': text(),
        'limitations': {'type': 'array', 'items': text()}, 'results': {'type': 'array', 'items': ref('MapLocation')}})
    params = copy.deepcopy(schema['paths']['/api/v1/demographics/search/']['get']['parameters'])
    params = [param for param in params if param['name'] not in ('page', 'page_size', 'sort')]
    for param in params:
        if param['name'] == 'level':
            param['schema']['default'] = 'city'
    for name, shape in [('event_id', integer()), ('radius_km', {'type': 'number', 'minimum': 0, 'maximum': 6000}),
        ('income_min', {'type': 'number', 'minimum': 0}), ('income_max', {'type': 'number', 'minimum': 0}),
        ('income_metric', text(enum=['responsible_income_mean', 'responsible_income_median'], default='responsible_income_mean'))]:
        params.append({'name': name, 'in': 'query', 'schema': shape})
    endpoint = operation('getDemographicMap', 'Map aligned census cohorts with locality income and event distance filters', 'Demographics', ref('DemographicMap'), parameters=params,
        description='Requires demographics:read, plus events:read when event_id is supplied. Owner-scoped and read-only. Returns at most 3000 candidate locations. Income filters apply mean/median monthly income of household responsible persons with income (nominal BRL 2022) to localities, never a joint age/income population count. Density is the aligned census cohort divided by full official territorial area. Anchors are official administrative seats. Missing coordinates are omitted with coverage counts. radius_km is straight-line event-to-seat distance, not driving distance or polygon intersection. Source population, history and event coordinates remain unchanged.')
    endpoint['x-required-permission'] = 'demographics:read'
    schema['paths']['/api/v1/demographics/map/'] = {'get': endpoint}
    schema['info']['version'] = '5.2.0'
