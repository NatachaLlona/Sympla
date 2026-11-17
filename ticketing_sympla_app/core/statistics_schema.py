"""OpenAPI descriptions for modular integrations and Census statistics."""
def extend(schema):
    from .openapi import obj, text, integer, ref, operation, paged, response, PAGINATION, NULL_DATETIME
    paths, schemas = schema['paths'], schema['components']['schemas']
    schema['tags'].append({'name': 'Demographics'})
    config = obj({
        'state_codes': {'type': 'array', 'items': text(pattern=r'^\d{2}$'), 'maxItems': 27},
        'municipality_codes': {'type': 'array', 'items': text(pattern=r'^\d{7}$'), 'maxItems': 10},
        'geographic_preset': text(enum=['capital_metropolitan_areas_2025'], description='All 27 capitals and members of their official metropolitan regions or RIDEs in corrected IBGE composition 2025. Use levels=[city] without explicit state or municipality codes.'),
        'levels': {'type': 'array', 'items': text(enum=['state', 'city', 'neighborhood'])},
        'include_districts_when_no_neighborhoods': {'type': 'boolean', 'default': True},
    })
    config.update({'additionalProperties': False, 'example': {'state_codes': ['35'], 'municipality_codes': ['3550308'], 'levels': ['state', 'city', 'neighborhood'], 'include_districts_when_no_neighborhoods': True}})
    for name in ('Integration', 'IntegrationInput', 'IntegrationUpdate'):
        schemas[name]['properties']['configuration'] = config
    schemas['IntegrationInput']['properties']['configuration']['description'] = 'Required scope for IBGE. Sympla accepts only an empty object. Codes are Census 2022 IBGE identifiers.'
    schemas['IntegrationProviderList']['properties']['results']['items']['properties']['domain'] = text(enum=['events', 'statistics'])
    schemas['SyncRun']['properties']['status']['enum'].append('partial')
    schemas['Geography'] = obj({'id': integer(), 'code': text(), 'name': text(), 'level': text(enum=['state', 'city', 'neighborhood', 'district']), 'parent_code': text(nullable=True), 'reference_year': integer()})
    schemas['Statistic'] = obj({'id': integer(), 'integration_id': text(format='uuid'), 'geography': ref('Geography'),
        'indicator': text(), 'indicator_name': text(), 'unit': text(), 'universe': text(), 'category': text(), 'category_name': text(),
        'age_min': integer(nullable=True), 'age_max': integer(nullable=True), 'period': text(),
        'value': {'nullable': True, 'oneOf': [{'type': 'integer'}, text(description='Exact decimal monetary value.')]},
        'source_status': text(), 'version': integer(), 'first_seen_at': NULL_DATETIME, 'last_seen_at': NULL_DATETIME, 'last_run_id': text(format='uuid')})
    schemas['StatisticVersion'] = obj({'id': integer(), 'version': integer(), 'value': text(nullable=True), 'source_status': text(), 'fingerprint': text(), 'run_id': text(format='uuid'), 'created_at': NULL_DATETIME})
    schemas['StatisticObservation'] = obj({'id': integer(), 'version': integer(), 'run_id': text(format='uuid'), 'collected_at': NULL_DATETIME,
        'source_url': text(), 'source_sha256': text(), 'source_columns': text(), 'reference_period': text(), 'transformation_version': text()})
    schemas['DataCoverage'] = obj({'id': integer(), 'run_id': text(format='uuid'), 'level': text(), 'parent_code': text(), 'status': text(), 'record_count': integer(), 'message': text()})
    for name in ('Geography', 'Statistic', 'StatisticVersion', 'StatisticObservation', 'DataCoverage'):
        schemas[name+'List'] = paged(name)
    routes = [
        ('/api/v1/geographies/', 'listGeographies', 'List imported geographical areas', 'GeographyList', ['level', 'code', 'parent_code']),
        ('/api/v1/demographics/', 'listDemographics', 'Read population, age and income statistics', 'StatisticList', ['integration_id', 'level', 'code', 'indicator', 'category', 'period']),
        ('/api/v1/demographics/{statistic_id}/versions/', 'listStatisticVersions', 'Read immutable statistic versions', 'StatisticVersionList', []),
        ('/api/v1/demographics/{statistic_id}/observations/', 'listStatisticObservations', 'Read source URLs, checksums and transformation lineage', 'StatisticObservationList', []),
        ('/api/v1/ibge/coverage/', 'listIbgeCoverage', 'Read availability and geographical coverage gaps', 'DataCoverageList', ['run_id']),
    ]
    for path, name, summary, result, filters in routes:
        parameters = list(PAGINATION) + [{'name': field, 'in': 'query', 'schema': text(format='uuid') if field in ('run_id', 'integration_id') else text()} for field in filters]
        if '{statistic_id}' in path:
            parameters.append({'name': 'statistic_id', 'in': 'path', 'required': True, 'schema': integer()})
        item = operation(name, summary, 'Demographics', ref(result), parameters=parameters,
            description='Requires demographics:read. Scoped to owned integrations. Null or suppressed values are never treated as zero. Districts are explicitly distinct from neighborhoods. Source units, universes and Census 2022 reference periods are retained.')
        item['x-required-permission'] = 'demographics:read'
        item['responses']['404'] = response('Statistic not found or inaccessible.', ref('Error'))
        paths[path] = {'get': item}
    schema['info']['version'] = '5.0.0'
    schema['info']['description'] += ' Sympla and IBGE imports run in independent provider containers. IBGE exposes relational population, age and income indicators with coverage and source lineage.'
