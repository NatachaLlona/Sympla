"""API contract for demographic cohort ranking and calendar-year alignment."""
def extend(schema):
    from .openapi import obj, text, integer, ref, operation, NULL_DATETIME, PAGINATION
    schemas, paths = schema['components']['schemas'], schema['paths']
    nullable_count = integer(nullable=True, minimum=0)
    schemas['CohortBand'] = obj({'source_band': text(), 'source_label': text(), 'source_age_min': integer(),
        'source_age_max': integer(nullable=True), 'aligned_age_min': integer(), 'aligned_age_max': integer(nullable=True),
        'count': nullable_count, 'fully_included': {'type': 'boolean'}, 'statistic_id': integer(nullable=True),
        'version': integer(nullable=True), 'last_seen_at': NULL_DATETIME, 'last_run_id': text(format='uuid', nullable=True)})
    schemas['CohortLocation'] = obj({'rank': integer(nullable=True), 'geography': ref('Geography'),
        'lower_bound': integer(minimum=0), 'upper_bound': nullable_count, 'exact_count': nullable_count,
        'estimated_count': {'type': 'number', 'nullable': True}, 'match': text(enum=['exact_band_match', 'bounded', 'incomplete_coverage']),
        'source_age_total': nullable_count, 'lower_share_percent': {'type': 'number', 'nullable': True},
        'upper_share_percent': {'type': 'number', 'nullable': True}, 'estimate_method': text(nullable=True),
        'flags': {'type': 'array', 'items': text()}, 'bands': {'type': 'array', 'items': ref('CohortBand')}})
    schemas['CohortSearchResult'] = obj({'count': integer(), 'page': integer(), 'page_size': integer(),
        'integration_id': text(format='uuid', nullable=True), 'years_advanced': integer(), 'method': text(),
        'rank_basis': text(), 'query': {'type': 'object'}, 'summary': obj({'exact_locations': integer(), 'bounded_locations': integer(), 'incomplete_locations': integer()}),
        'limitations': {'type': 'array', 'items': text()}, 'results': {'type': 'array', 'items': ref('CohortLocation')}, 'empty_reason': text()})
    parameters = list(PAGINATION)
    for name, shape in [
        ('integration_id', text(format='uuid')), ('source_year', integer(default=2022)), ('target_year', integer(description='Defaults to the current calendar year in Europe/Lisbon; cannot precede the source year.')),
        ('age_min', integer(minimum=0, maximum=130)), ('age_max', integer(minimum=0, maximum=130)),
        ('level', text(enum=['state', 'city', 'neighborhood', 'district'], default='district')),
        ('state_code', text(pattern=r'^\d{2}$')), ('city_code', text(pattern=r'^\d{7}$')),
        ('estimate', {'type': 'boolean', 'default': False}), ('sort', text(enum=['lower_bound', 'upper_bound', 'estimate', 'share'], default='lower_bound')),
    ]:
        parameters.append({'name': name, 'in': 'query', 'schema': shape})
    search = operation('searchDemographicCohorts', 'Rank places by an age-aligned census cohort', 'Demographics', ref('CohortSearchResult'), parameters=parameters,
        description='Requires demographics:read. Calendar-year shift = target_year - source_year. Source rows are never rewritten. Exact counts refer only to fully matched published cohorts; deaths, migration and post-census births are not modeled. Partial bands return bounds; estimate=true permits a uniform-within-band estimate, except for open-ended or missing cohorts. Multiple imported integrations require an explicit integration_id. Share uses the source age-tabulated total, not a current population total.')
    search['x-required-permission'] = 'demographics:read'
    paths['/api/v1/demographics/search/'] = {'get': search}
    options = operation('getDemographicExplorerOptions', 'Read available cohort sources and age bands', 'Demographics',
        obj({'current_year': integer(), 'source_years': {'type': 'array', 'items': integer()}, 'integrations': {'type': 'array', 'items': obj({'id': text(format='uuid'), 'name': text()})},
             'source_bands': {'type': 'array', 'items': obj({'code': text(), 'name': text(), 'age_min': integer(), 'age_max': integer(nullable=True)})},
             'method': text(), 'limitations': {'type': 'array', 'items': text()}}), description='Requires demographics:read. Returns only sources with imported age statistics owned by the API account.')
    options['x-required-permission'] = 'demographics:read'
    paths['/api/v1/demographics/explorer-options/'] = {'get': options}
    paths['/api/v1/geographies/']['get']['parameters'].append({'name': 'integration_id', 'in': 'query', 'schema': text(format='uuid')})
    paths['/api/v1/ibge/coverage/']['get']['parameters'] += [
        {'name': 'integration_id', 'in': 'query', 'schema': text(format='uuid')}, {'name': 'latest', 'in': 'query', 'schema': {'type': 'boolean', 'default': False}}]
    schema['info']['version'] = '5.1.0'
