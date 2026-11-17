"""Census population, age and income import using official geographical definitions."""
import re
from decimal import Decimal, InvalidOperation
from .catalog import archive, AGE_BANDS
from .http import download, csv_rows, json_document
from .metropolitan import PRESET, catalog as metropolitan_catalog, municipality_codes
from ...sync_exception import SyncError


def configuration(value):
    if not isinstance(value, dict) or value.keys() - {'state_codes', 'municipality_codes', 'levels', 'include_districts_when_no_neighborhoods', 'geographic_preset'}:
        raise ValueError('Provide documented IBGE scope fields only.')
    result = dict(value)
    preset = result.get('geographic_preset')
    if 'geographic_preset' in result and preset != PRESET:
        raise ValueError(f'geographic_preset must be {PRESET}.')
    for field, pattern, limit in [('state_codes', r'\d{2}', 27), ('municipality_codes', r'\d{7}', 10)]:
        codes = result.get(field, [])
        if not isinstance(codes, list) or len(codes) > limit or any(not isinstance(code, str) or not re.fullmatch(pattern, code) for code in codes) or len(set(codes)) != len(codes):
            raise ValueError(f'{field} must contain unique official IBGE codes (maximum {limit}).')
        result[field] = sorted(codes)
    levels = result.get('levels', ['city'] if preset else ['state', 'city', 'neighborhood'])
    if not isinstance(levels, list) or not levels or any(level not in ('state', 'city', 'neighborhood') for level in levels) or len(set(levels)) != len(levels):
        raise ValueError('levels must contain unique state, city or neighborhood values.')
    if preset and (result['state_codes'] or result['municipality_codes'] or levels != ['city']):
        raise ValueError('The capital metropolitan preset uses city level only and cannot be combined with explicit codes.')
    if not preset and not result['state_codes'] and not result['municipality_codes']:
        raise ValueError('Choose at least one state or municipality code.')
    if not preset and any(level in levels for level in ('city', 'neighborhood')) and not result['municipality_codes']:
        raise ValueError('Choose municipality_codes for city or neighborhood imports.')
    result['levels'] = levels
    fallback = result.get('include_districts_when_no_neighborhoods', True)
    if type(fallback) is not bool:
        raise ValueError('include_districts_when_no_neighborhoods must be a boolean.')
    result['include_districts_when_no_neighborhoods'] = fallback
    return result


def number(value):
    if value in ('X', 'x', '...', '..', '.', '', None):
        return None, 'not_available' if value != 'X' and value != 'x' else 'suppressed'
    if value == '-':
        return Decimal(0), 'available'
    try:
        result = Decimal(str(value).replace(',', '.'))
        if not result.is_finite() or result < 0 or result >= Decimal('1000000000000000000'):
            raise InvalidOperation()
        return result, 'available'
    except InvalidOperation:
        raise SyncError('ibge_invalid_response') from None


class IbgeConnector:
    code = 'ibge'
    version = 'ibge.census2022.v2'
    credential_scope = 'public'
    domain = 'statistics'
    running_slot = 2
    validate_configuration = staticmethod(configuration)

    def configuration_error(self, integration, api_account):
        try:
            configuration(integration.configuration)
        except ValueError:
            return 'ibge_configuration'
        return None

    def collect(self, integration, api_account):
        scope = configuration(integration.configuration)
        municipalities = set(scope['municipality_codes'])
        if scope.get('geographic_preset') == PRESET:
            municipalities = municipality_codes()
        states = set(scope['state_codes']) | {code[:2] for code in municipalities}
        result = {'records': [], 'sources': [], 'coverage': []}
        if scope.get('geographic_preset') == PRESET:
            catalog = metropolitan_catalog()
            result['sources'].append({'code': 'metropolitan_composition_2025', 'url': catalog['source_url'],
                'sha256': catalog['source_sha256'], 'reference_period': str(catalog['composition_year'])})
            for capital in catalog['capitals']:
                areas = capital['areas']
                count = len({code for area in areas for code in area['members']} or {capital['code']})
                description = '; '.join(area['name'] for area in areas) if areas else 'No official metropolitan or RIDE membership in this edition; capital imported individually.'
                result['coverage'].append({'level': 'city', 'parent_code': capital['code'], 'status': 'available',
                    'record_count': count, 'message': f"{capital['name']} ({capital['state']}): {description} Composition 2025, corrected 2026-07-29. Demographic reference remains 2022."})
        cache = {}

        def source(level, topic):
            key = f'{level}_{topic}'
            if key not in cache:
                url = archive(level, topic)
                content, digest = download(url)
                cache[key] = list(csv_rows(content))
                result['sources'].append({'code': key, 'url': url, 'sha256': digest})
            return key, cache[key]

        def emit(geography, indicator, category, raw, source_code, columns):
            value, status = number(raw)
            result['records'].append({'geography': geography, 'indicator': indicator, 'category': category,
                'value': str(value) if value is not None else None, 'source_status': status,
                'source': source_code, 'source_columns': columns})

        # Municipal base rows also provide the authoritative state/municipality hierarchy.
        _, base_rows = source('city', 'base')
        city_metadata = {row['CD_MUN']: row for row in base_rows}
        if municipalities - city_metadata.keys() or states - {row['CD_UF'] for row in base_rows}:
            raise SyncError('ibge_unknown_geography')

        def geography(level, code, row):
            state = {'code': row['CD_UF'], 'level': 'state', 'name': row['NM_UF'], 'parent': None}
            city = {'code': row['CD_MUN'], 'level': 'city', 'name': row['NM_MUN'], 'parent': state}
            if level == 'state':
                return state
            if level == 'city':
                return city
            key = 'BAIRRO' if level == 'neighborhood' else 'DIST'
            return {'code': code, 'level': level, 'name': row['NM_' + key], 'parent': city}

        def collect_level(level, selected):
            key = 'CD_MUN' if level == 'city' else ('CD_BAIRRO' if level == 'neighborhood' else 'CD_DIST')
            base_code, rows = source(level, 'base')
            chosen = [row for row in rows if row['CD_MUN'] in selected]
            chosen_by_code = {row[key]: row for row in chosen}
            geographies = {row[key]: geography(level, row[key], row) for row in chosen}
            for row in chosen:
                emit(geographies[row[key]], 'population', 'total', row['V0001'], base_code, 'V0001')
            age_code, age_rows = source(level, 'age')
            age_ids = set()
            for row in age_rows:
                if row[key] in geographies:
                    age_ids.add(row[key])
                    emit(geographies[row[key]], 'age_population', 'total', row['V01006'], age_code, 'V01006')
                    for category, _, _, _, column in AGE_BANDS:
                        emit(geographies[row[key]], 'age_population', category, row[column], age_code, column)
                    base_row = chosen_by_code[row[key]]
                    if number(row['V01006'])[0] != number(base_row['V0001'])[0]:
                        result['coverage'].append({'level': level, 'parent_code': row[key], 'status': 'age_universe_differs', 'record_count': 1, 'message': 'The published age total differs from the revised basic population total. Use the age total as the denominator; no ages are inferred.'})
            income_code, income_rows = source(level, 'income')
            income_ids = set()
            for row in income_rows:
                if row[key] in geographies:
                    income_ids.add(row[key])
                    for indicator, column in [('responsible_income_mean', 'V06004'), ('responsible_income_median', 'V06006')]:
                        emit(geographies[row[key]], indicator, 'total', row[column], income_code, column)
            for topic, present, source_code, metrics in [
                ('age', age_ids, age_code, [('age_population', category, column) for category, _, _, _, column in AGE_BANDS] + [('age_population', 'total', 'V01006')]),
                ('income', income_ids, income_code, [('responsible_income_mean', 'total', 'V06004'), ('responsible_income_median', 'total', 'V06006')]),
            ]:
                for code in geographies.keys() - present:
                    for indicator, category, column in metrics:
                        emit(geographies[code], indicator, category, None, source_code, column)
                    result['coverage'].append({'level': level, 'parent_code': code, 'status': f'{topic}_not_available', 'record_count': 0, 'message': 'No row was published for this geography in the selected official source. Values remain null.'})
            return chosen

        if 'city' in scope['levels']:
            rows = collect_level('city', municipalities)
            for code in sorted(municipalities):
                result['coverage'].append({'level': 'city', 'parent_code': code, 'status': 'available', 'record_count': sum(row['CD_MUN'] == code for row in rows), 'message': 'Official Census 2022 municipal aggregates.'})
        if 'state' in scope['levels']:
            base_code, rows = source('city', 'base')
            age_code, age_rows = source('city', 'age')
            age_by_city = {row['CD_MUN']: row for row in age_rows}
            for state_code in sorted(states):
                selected = [row for row in rows if row['CD_UF'] == state_code]
                location = geography('state', state_code, selected[0])
                population = [number(row['V0001'])[0] for row in selected]
                emit(location, 'population', 'total', str(sum(population)) if None not in population else None, base_code, 'SUM(V0001):all_municipalities_in_state')
                for category, _, _, _, column in AGE_BANDS:
                    values = [number(age_by_city[row['CD_MUN']][column])[0] for row in selected]
                    emit(location, 'age_population', category, str(sum(values)) if None not in values else None, age_code, f'SUM({column}):all_municipalities_in_state')
                age_totals = [number(age_by_city[row['CD_MUN']]['V01006'])[0] for row in selected]
                emit(location, 'age_population', 'total', str(sum(age_totals)) if None not in age_totals else None, age_code, 'SUM(V01006):all_municipalities_in_state')
                if None not in population and None not in age_totals and sum(population) != sum(age_totals):
                    result['coverage'].append({'level': 'state', 'parent_code': state_code, 'status': 'age_universe_differs', 'record_count': 1, 'message': 'Published age totals and revised basic population totals differ; each indicator retains its source universe.'})
                self.state_income(state_code, location, result, emit)
                result['coverage'].append({'level': 'state', 'parent_code': state_code, 'status': 'available', 'record_count': 1, 'message': 'Population and age are sums of all official municipalities in the state; income source is reported separately.'})
        if 'neighborhood' in scope['levels']:
            rows = collect_level('neighborhood', municipalities)
            missing = set()
            for code in sorted(municipalities):
                count = sum(row['CD_MUN'] == code for row in rows)
                if not count:
                    missing.add(code)
                result['coverage'].append({'level': 'neighborhood', 'parent_code': code, 'status': 'available' if count else 'not_available', 'record_count': count, 'message': 'Official IBGE neighborhoods only; districts are never relabeled as neighborhoods.'})
            if missing and scope['include_districts_when_no_neighborhoods']:
                rows = collect_level('district', missing)
                for code in sorted(missing):
                    result['coverage'].append({'level': 'district', 'parent_code': code, 'status': 'available', 'record_count': sum(row['CD_MUN'] == code for row in rows), 'message': 'Explicit district fallback for a municipality without official neighborhood records in this product.'})
        if len(result['records']) > 50000:
            raise SyncError('ibge_response_limit')
        return result

    def state_income(self, state_code, geography, result, emit):
        # Means and medians cannot be reconstructed from municipal means/medians.
        base = 'https://servicodados.ibge.gov.br/api/v3/agregados/10295'
        try:
            metadata_content, _ = download(base + '/metadados')
            metadata = json_document(metadata_content)
            variables = metadata['variaveis']
            classifications = []
            for classification in metadata['classificacoes']:
                totals = [item['id'] for item in classification['categorias'] if item['nome'].casefold() == 'total']
                if len(totals) != 1:
                    raise SyncError('ibge_invalid_response')
                classifications.append(f"{classification['id']}[{totals[0]}]")
            pending, found = [], set()
            for variable in variables:
                name = variable['nome'].casefold()
                kind = 'mean' if 'médio' in name else ('median' if 'mediano' in name else None)
                if not kind or 'rendimento' not in name:
                    continue
                if variable.get('unidade') and variable['unidade'].casefold() not in ('reais', 'real', 'r$'):
                    continue
                if kind in found:
                    raise SyncError('ibge_invalid_response')
                url = f"{base}/periodos/2022/variaveis/{int(variable['id'])}?localidades=N3[{state_code}]&classificacao=" + '|'.join(classifications)
                content, digest = download(url)
                document = json_document(content)
                entries = [series for item in document for outcome in item['resultados'] for series in outcome['series'] if str(series['localidade']['id']) == state_code]
                if len(entries) != 1:
                    raise SyncError('ibge_invalid_response')
                source_code = f'state_income_{state_code}_{kind}'
                raw_value = entries[0]['serie']['2022']
                number(raw_value)
                pending.append((kind, source_code, url, digest, raw_value, str(variable['id'])))
                found.add(kind)
            if found != {'mean', 'median'}:
                raise SyncError('ibge_invalid_response')
            for kind, source_code, url, digest, raw_value, variable_id in pending:
                result['sources'].append({'code': source_code, 'url': url, 'sha256': digest})
                emit(geography, f'household_per_capita_income_{kind}', 'total', raw_value, source_code, variable_id)
        except (SyncError, KeyError, TypeError, ValueError) as exc:
            code = str(exc) if isinstance(exc, SyncError) else 'ibge_invalid_response'
            result['coverage'].append({'level': 'state', 'parent_code': state_code, 'status': 'income_not_available', 'record_count': 0, 'message': f'Official state income API unavailable ({code}). No state income is inferred from municipal averages or medians.'})
