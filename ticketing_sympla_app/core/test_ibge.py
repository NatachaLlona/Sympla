import csv
import hashlib
import io
import json
import zipfile
from datetime import time, timedelta
from unittest.mock import patch
from django.db import DatabaseError, transaction
from django.test import TestCase, SimpleTestCase
from django.utils import timezone
from .credentials import configure_client
from .models import (Role, AccessToken, Integration, Statistic, StatisticVersion, StatisticObservation,
                     Geography, ImportSource, DataCoverage, Schedule, SyncRun)
from .services import enqueue, process_one, claim_run, enqueue_due
from .statistics_services import persist_statistics
from .integration_modules.ibge.catalog import AGE_BANDS, archive
from .integration_modules.ibge.connector import IbgeConnector, number, configuration
from .integration_modules.ibge.http import csv_rows
from .sync_exception import SyncError


def zipped(rows):
    output = io.BytesIO()
    text = io.StringIO()
    writer = csv.DictWriter(text, fieldnames=list(rows[0]), delimiter=';')
    writer.writeheader()
    writer.writerows(rows)
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as result:
        result.writestr('official.csv', text.getvalue().encode('cp1252'))
    return output.getvalue()


class IbgeTests(TestCase):
    def setUp(self):
        self.api_account = configure_client('ibge-client', 'PublicData1!')
        self.api_account.is_superuser = True
        self.api_account.save()
        self.scope = {'state_codes': ['35'], 'municipality_codes': ['3550308'], 'levels': ['state', 'city', 'neighborhood']}
        self.integration = Integration.objects.create(owner=self.api_account, name='IBGE test', provider='ibge', configuration=self.scope)
        self.files = {}
        city = {'CD_MUN': '3550308', 'NM_MUN': 'São Paulo', 'CD_UF': '35', 'NM_UF': 'São Paulo', 'v0001': '100'}
        other = {**city, 'CD_MUN': '3509502', 'NM_MUN': 'Campinas', 'v0001': '50'}
        district = {**city, 'CD_DIST': '355030801', 'NM_DIST': 'Água Rasa', 'v0001': '100'}
        neighborhood = {**other, 'CD_BAIRRO': '3509502001', 'NM_BAIRRO': 'Centro'}
        for level, rows, key in [('city', [city, other], 'CD_MUN'), ('district', [district], 'CD_DIST'), ('neighborhood', [neighborhood], 'CD_BAIRRO')]:
            self.files[archive(level, 'base')] = zipped(rows)
            self.files[archive(level, 'age')] = zipped([{key: row[key], 'V01006': row['v0001'], **{column: row['v0001'] if index == 0 else '0' for index, (_, _, _, _, column) in enumerate(AGE_BANDS)}} for row in rows])
            self.files[archive(level, 'income')] = zipped([{key: row[key], 'V06004': '2500,50', 'V06006': '2000'} for row in rows])
        self.header = self.token(self.api_account)

    def token(self, api_account):
        value = 'ibge-test-' + str(api_account.identifier)
        AccessToken.objects.create(token_hash=hashlib.sha256(value.encode()).hexdigest(), api_account=api_account,
            credential_version=api_account.credential_version, expires_at=timezone.now() + timedelta(hours=1))
        return {'HTTP_AUTHORIZATION': 'Bearer ' + value}

    def download(self, url):
        if url.endswith('/metadados'):
            content = json.dumps({'variaveis': [{'id': 1, 'nome': 'Rendimento médio'}, {'id': 2, 'nome': 'Rendimento mediano'}], 'classificacoes': []}).encode()
        elif '/variaveis/' in url:
            content = json.dumps([{'resultados': [{'series': [{'localidade': {'id': '35'}, 'serie': {'2022': '1234.50'}}]}]}]).encode()
        else:
            content = self.files[url]
        return content, hashlib.sha256(content).hexdigest()

    def collect(self):
        with patch('core.integration_modules.ibge.connector.download', side_effect=self.download):
            return IbgeConnector().collect(self.integration, self.api_account)

    def run_import(self):
        enqueue('qa', owner=self.api_account, integration=self.integration)
        with patch('core.integration_modules.ibge.connector.download', side_effect=self.download):
            return process_one('ibge')

    def test_state_city_and_honest_district_fallback_are_relational(self):
        run = self.run_import()
        self.assertEqual(run.status, 'partial')
        self.assertFalse(Geography.objects.filter(level='neighborhood').exists())
        self.assertEqual(set(Geography.objects.values_list('level', flat=True)), {'state', 'city', 'district'})
        district = Geography.objects.get(level='district')
        self.assertEqual(district.parent.code, '3550308')
        state_population = Statistic.objects.get(geography__level='state', category__indicator_id='population')
        self.assertEqual(state_population.value, 150)
        self.assertTrue(DataCoverage.objects.filter(run=run, level='neighborhood', status='not_available').exists())
        self.assertEqual(Statistic.objects.get(geography__level='city', category__indicator_id='responsible_income_mean').value, 2500.5)
        self.assertEqual(Statistic.objects.get(geography__level='state', category__indicator_id='household_per_capita_income_mean').value, 1234.5)
        self.assertEqual(Statistic.objects.count(), 45)
        self.assertEqual(StatisticObservation.objects.count(), 45)
        self.assertFalse(self.api_account.sympla_token_encrypted)

    def test_actual_neighborhoods_remain_neighborhoods(self):
        self.integration.configuration = {'municipality_codes': ['3509502'], 'levels': ['neighborhood']}
        self.integration.save()
        self.assertEqual(self.run_import().status, 'success')
        self.assertTrue(Geography.objects.filter(level='neighborhood', code='3509502001', parent__code='3509502').exists())
        self.assertFalse(Geography.objects.filter(level='district').exists())

    def test_unchanged_values_have_observations_without_extra_versions(self):
        self.run_import()
        first = StatisticVersion.objects.count()
        self.run_import()
        self.assertEqual(StatisticVersion.objects.count(), first)
        self.assertEqual(StatisticObservation.objects.count(), first * 2)
        self.assertEqual(ImportSource.objects.count(), 22)

    def test_changed_values_append_versions(self):
        self.run_import()
        rows = [{'CD_MUN': '3550308', 'V06004': '2600,00', 'V06006': '2000'}, {'CD_MUN': '3509502', 'V06004': '2500,50', 'V06006': '2000'}]
        self.files[archive('city', 'income')] = zipped(rows)
        self.run_import()
        statistic = Statistic.objects.get(geography__code='3550308', category__indicator_id='responsible_income_mean')
        self.assertEqual(statistic.version, 2)
        self.assertEqual(StatisticVersion.objects.filter(statistic=statistic).count(), 2)

    def test_state_income_failure_preserves_other_data_with_explicit_coverage(self):
        original = self.download
        def unavailable(url):
            if 'servicodados' in url:
                raise SyncError('ibge_connection_error')
            return original(url)
        enqueue('qa', owner=self.api_account, integration=self.integration)
        with patch('core.integration_modules.ibge.connector.download', side_effect=unavailable):
            run = process_one('ibge')
        self.assertEqual(run.status, 'partial')
        self.assertTrue(DataCoverage.objects.filter(run=run, status='income_not_available').exists())
        self.assertFalse(Statistic.objects.filter(geography__level='state', category__indicator__code__startswith='household').exists())
        self.assertTrue(Statistic.objects.filter(geography__level='city', category__indicator_id='responsible_income_mean').exists())

    def test_owner_and_integration_revision_are_rechecked_before_commit(self):
        batch = self.collect()
        enqueue('qa', owner=self.api_account, integration=self.integration)
        run = claim_run('ibge')
        Integration.objects.filter(pk=self.integration.pk).update(revision=2)
        with self.assertRaises(SyncError):
            persist_statistics(run.pk, batch)
        self.assertFalse(Statistic.objects.exists())
        self.assertFalse(ImportSource.objects.exists())

    def test_state_income_failure_mid_fetch_does_not_leave_partial_state_rows(self):
        original = self.download
        def fail_median(url):
            if '/variaveis/2?' in url:
                raise SyncError('ibge_connection_error')
            return original(url)
        with patch('core.integration_modules.ibge.connector.download', side_effect=fail_median):
            batch = IbgeConnector().collect(self.integration, self.api_account)
        self.assertFalse(any(row['indicator'].startswith('household_per_capita') for row in batch['records']))
        self.assertFalse(any(source['code'].startswith('state_income') for source in batch['sources']))
        self.assertTrue(any(item['status'] == 'income_not_available' for item in batch['coverage']))

    def test_invalid_batch_rolls_back_all_statistical_tables(self):
        batch = self.collect()
        batch['records'].append(batch['records'][0])
        enqueue('qa', owner=self.api_account, integration=self.integration)
        run = claim_run('ibge')
        with self.assertRaises(SyncError):
            persist_statistics(run.pk, batch)
        for model in (Statistic, StatisticVersion, StatisticObservation, ImportSource, Geography):
            self.assertFalse(model.objects.exists())

    def test_provider_workers_claim_only_their_own_jobs(self):
        sympla_run = enqueue('qa', owner=self.api_account)
        ibge_run = enqueue('qa', owner=self.api_account, integration=self.integration)
        self.assertEqual(claim_run('ibge').pk, ibge_run.pk)
        self.assertEqual(claim_run('sympla').pk, sympla_run.pk)
        self.assertEqual(set(SyncRun.objects.filter(status='running').values_list('running_slot', flat=True)), {1, 2})
        self.assertIsNone(claim_run('ibge'))

    def test_schedulers_filter_provider(self):
        for integration in (self.integration, Integration.objects.get(owner=self.api_account, provider='sympla')):
            Schedule.objects.create(owner=self.api_account, integration=integration, time=time(10), timezone='UTC', next_run_at=timezone.now()-timedelta(minutes=1), created_by='qa')
        self.assertEqual(enqueue_due(provider='ibge'), 1)
        self.assertEqual(SyncRun.objects.get().integration.provider, 'ibge')

    def test_read_api_requires_demographics_permission_and_is_owner_scoped(self):
        self.run_import()
        response = self.client.get('/api/v1/demographics/?level=city&indicator=population', **self.header)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['results'][0]['value'], 100)
        statistic = Statistic.objects.first()
        provenance = self.client.get(f'/api/v1/demographics/{statistic.pk}/observations/', **self.header).json()['results'][0]
        self.assertTrue(provenance['source_url'].startswith('https://'))
        self.assertEqual(len(provenance['source_sha256']), 64)
        other = configure_client('other-ibge', 'OtherData1!')
        header = self.token(other)
        self.assertEqual(self.client.get('/api/v1/demographics/', **header).status_code, 403)
        role = Role.objects.create(name='Demographics reader')
        role.permissions.set(['demographics:read'])
        other.role = role
        other.save()
        self.assertEqual(self.client.get('/api/v1/demographics/', **header).json()['count'], 0)
        self.assertEqual(self.client.get('/api/v1/geographies/', **header).json()['count'], 0)
        self.assertEqual(self.client.get(f'/api/v1/demographics/{statistic.pk}/versions/', **header).status_code, 404)
        self.assertEqual(self.client.get('/api/v1/ibge/coverage/', **header).json()['count'], 0)

    def test_new_statistical_history_is_append_only(self):
        self.run_import()
        for model in (StatisticVersion, StatisticObservation, ImportSource, DataCoverage):
            for operation in (lambda model=model: model.objects.all().delete(), lambda model=model: model.objects.update(run_id=SyncRun.objects.first().pk)):
                with self.assertRaises(DatabaseError), transaction.atomic():
                    operation()

    def test_coverage_flags_age_denominator_difference(self):
        self.files[archive('city', 'age')] = zipped([{'CD_MUN': code, 'V01006': str(total-1), **{column: str(total-1) if index == 0 else '0' for index, (_, _, _, _, column) in enumerate(AGE_BANDS)}} for code, total in [('3550308', 100), ('3509502', 50)]])
        self.run_import()
        self.assertTrue(DataCoverage.objects.filter(level='city', status='age_universe_differs').exists())
        self.assertEqual(Statistic.objects.get(geography__code='3550308', category__indicator_id='age_population', category__code='total').value, 99)

    def test_integration_crud_validates_scope(self):
        for config in ({}, {'municipality_codes': ['http://localhost']}, {'municipality_codes': ['3550308'], 'url': 'https://elsewhere.test'}):
            response = self.client.post('/api/v1/integrations/', data=json.dumps({'name': 'Invalid IBGE', 'provider': 'ibge', 'configuration': config}), content_type='application/json', **self.header)
            self.assertEqual(response.status_code, 400)
        response = self.client.post('/api/v1/integrations/', data=json.dumps({'name': 'Valid IBGE', 'provider': 'ibge', 'configuration': self.scope}), content_type='application/json', **self.header)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['configuration']['municipality_codes'], ['3550308'])


class IbgeParsingTests(SimpleTestCase):
    def test_decimal_and_missing_symbols(self):
        self.assertEqual(number('1,25')[0], 1.25)
        self.assertEqual(number('-')[0], 0)
        self.assertEqual(number('X'), (None, 'suppressed'))
        self.assertEqual(number('...'), (None, 'not_available'))
        for raw in ('NaN', 'Infinity', '-1', 'arbitrary'):
            with self.assertRaises(SyncError):
                number(raw)

    def test_zip_csv_decodes_official_accents_without_extracting_files(self):
        content = zipped([{'NM_MUN': 'São Paulo', 'v0001': '100'}])
        self.assertEqual(list(csv_rows(content)), [{'NM_MUN': 'São Paulo', 'V0001': '100'}])
        with self.assertRaises(SyncError):
            list(csv_rows(b'not a ZIP'))

    def test_configuration_cannot_select_urls_or_unbounded_municipalities(self):
        for value in (None, {'url': 'https://localhost'}, {'municipality_codes': [str(3550308+i) for i in range(11)]}):
            with self.assertRaises(ValueError):
                configuration(value)
