from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
import hashlib
from datetime import timedelta
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from .cohort_search import align_cohort
from .integration_modules.ibge.catalog import AGE_BANDS
from .models import (AccessToken, Role, Geography, Integration, Statistic, SyncRun, StatisticalCategory, DataCoverage)
from .credentials import configure_client
from .statistics_services import seed_catalog


def band_rows(values=None):
    values = values or {'0_4': 100, '5_9': 200, '10_14': 700, 'total': 1000}
    return [SimpleNamespace(pk=index, category=SimpleNamespace(code=code),
        value=Decimal(values.get(code, 0)) if values.get(code, 0) is not None else None,
        source_status='available' if values.get(code, 0) is not None else 'suppressed',
        version=1, last_seen_at=None, last_run_id=None)
        for index, code in enumerate([item[0] for item in AGE_BANDS]+['total'], 1)]


class CohortMathTests(SimpleTestCase):
    def test_four_year_shift_preserves_exact_published_cohort(self):
        rows = band_rows()
        result = align_cohort(rows, 2022, 2026, 4, 8)
        self.assertEqual(result['exact_count'], 100)
        self.assertEqual(result['lower_bound'], result['upper_bound'])
        self.assertEqual(result['lower_share_percent'], 10)
        self.assertEqual(result['bands'][0]['source_age_min'], 0)
        self.assertEqual(result['bands'][0]['aligned_age_max'], 8)
        self.assertEqual(rows[0].value, 100)

    def test_shift_uses_target_year_instead_of_a_fixed_four_year_constant(self):
        self.assertEqual(align_cohort(band_rows(), 2022, 2027, 5, 9)['exact_count'], 100)
        self.assertEqual(align_cohort(band_rows(), 2022, 2022, 0, 4)['exact_count'], 100)

    def test_partial_bands_have_bounds_and_no_silent_point_estimate(self):
        result = align_cohort(band_rows(), 2022, 2026, 6, 10)
        self.assertEqual((result['lower_bound'], result['upper_bound']), (0, 300))
        self.assertIsNone(result['exact_count'])
        self.assertIsNone(result['estimated_count'])
        self.assertEqual(result['match'], 'bounded')

    def test_opt_in_uniform_estimate_is_weighted_by_intersecting_years(self):
        result = align_cohort(band_rows(), 2022, 2026, 6, 10, True)
        self.assertEqual(result['estimated_count'], 140)
        self.assertEqual(result['estimate_method'], 'uniform_within_closed_age_band')

    def test_multiple_full_bands_are_summed_without_double_counting(self):
        result = align_cohort(band_rows(), 2022, 2026, 4, 13)
        self.assertEqual(result['exact_count'], 300)
        self.assertEqual(result['source_age_total'], 1000)

    def test_post_census_births_are_unknown_rather_than_zero(self):
        result = align_cohort(band_rows(), 2022, 2026, 0, 3, True)
        self.assertIsNone(result['upper_bound'])
        self.assertIsNone(result['estimated_count'])
        self.assertIsNone(result['exact_count'])
        self.assertIn('post_census_births', result['flags'])

    def test_mixed_known_and_post_census_births_remains_incomplete(self):
        result = align_cohort(band_rows(), 2022, 2026, 0, 13, True)
        self.assertEqual(result['lower_bound'], 300)
        self.assertIsNone(result['upper_bound'])
        self.assertEqual(result['match'], 'incomplete_coverage')

    def test_missing_or_suppressed_age_band_is_not_zero(self):
        rows = band_rows({'0_4': None, 'total': 1000})
        result = align_cohort(rows, 2022, 2026, 4, 8)
        self.assertIsNone(result['upper_bound'])
        self.assertIn('missing_or_suppressed_band', result['flags'])
        rows = [row for row in band_rows() if row.category.code != '0_4']
        self.assertIsNone(align_cohort(rows, 2022, 2026, 4, 8)['upper_bound'])

    def test_open_ended_age_band_cannot_have_a_uniform_point_estimate(self):
        result = align_cohort(band_rows({'70_plus': 100, 'total': 100}), 2022, 2026, 80, 90, True)
        self.assertEqual(result['upper_bound'], 100)
        self.assertIsNone(result['estimated_count'])
        self.assertIn('open_ended_band_estimate_unavailable', result['flags'])

    def test_true_zero_is_exact_and_a_zero_denominator_does_not_divide(self):
        result = align_cohort(band_rows({'total': 0}), 2022, 2026, 4, 8)
        self.assertEqual(result['exact_count'], 0)
        self.assertIsNone(result['lower_share_percent'])


@patch('core.cohort_search.current_year', return_value=2026)
class CohortApiTests(TestCase):
    def setUp(self):
        import uuid
        seed_catalog()
        self.api_account = configure_client('cohort-client', 'CohortPass1!')
        self.api_account.is_superuser = True
        self.api_account.save()
        self.integration = Integration.objects.create(owner=self.api_account, name='Cohort source', provider='ibge')
        self.run = SyncRun.objects.create(id=uuid.uuid4(), owner=self.api_account, integration=self.integration, source='manual', status='success', actor='qa')
        self.state = Geography.objects.create(code='35', level='state', name='São Paulo')
        self.city = Geography.objects.create(code='3550308', level='city', name='São Paulo', parent=self.state)
        for index, count in enumerate([100, 300, 300], 1):
            geography = Geography.objects.create(code=f'35503080{index}', level='district', name=f'District {index}', parent=self.city)
            for code, value in [('0_4', count), ('5_9', 200), ('total', 1000)]:
                Statistic.objects.create(integration=self.integration, geography=geography,
                    category=StatisticalCategory.objects.get(indicator_id='age_population', code=code),
                    value=value, fingerprint='fixture', last_run=self.run)
        self.header = self.token(self.api_account)

    def token(self, api_account):
        token = 'cohort-test-' + str(api_account.identifier)
        AccessToken.objects.create(api_account=api_account, token_hash=hashlib.sha256(token.encode()).hexdigest(),
            credential_version=api_account.credential_version, expires_at=timezone.now()+timedelta(hours=1))
        return {'HTTP_AUTHORIZATION': 'Bearer '+token}

    def get(self, extra=None, header=None):
        return self.client.get('/api/v1/demographics/search/', {'age_min': '4', 'age_max': '8', **(extra or {})}, **(header or self.header))

    def test_current_year_alignment_ranking_ties_and_pagination(self, clock):
        response = self.get({'page_size': '2'}).json()
        self.assertEqual(response['years_advanced'], 4)
        self.assertEqual(response['count'], 3)
        self.assertEqual([row['exact_count'] for row in response['results']], [300, 300])
        self.assertEqual([row['rank'] for row in response['results']], [1, 1])
        self.assertEqual(self.get({'page': '2', 'page_size': '2'}).json()['results'][0]['rank'], 3)

    def test_search_does_not_rewrite_source_statistics(self, clock):
        before = list(Statistic.objects.order_by('id').values())
        self.assertEqual(self.get({'age_min': '6', 'age_max': '10', 'estimate': 'true', 'sort': 'estimate'}).status_code, 200)
        self.assertEqual(before, list(Statistic.objects.order_by('id').values()))

    def test_validation_rejects_bad_ranges_future_years_and_unknown_filters(self, clock):
        for extra in [{'age_max': '2'}, {'age_min': '4.2'}, {'target_year': '2027'}, {'target_year': '2021'},
                      {'estimate': 'yes'}, {'sort': 'estimate'}, {'state_code': '355'}, {'city_code': '3304557', 'state_code': '35'},
                      {'level': 'state', 'city_code': '3550308'}, {'unknown': 'value'}, {'page_size': '1000'}]:
            with self.subTest(extra=extra):
                self.assertEqual(self.get(extra).status_code, 400)

    def test_api_permission_and_tenant_isolation(self, clock):
        other = configure_client('other-cohort', 'OtherPass1!')
        header = self.token(other)
        self.assertEqual(self.get(header=header).status_code, 403)
        role = Role.objects.create(name='Cohort reader')
        role.permissions.set(['demographics:read'])
        other.role = role
        other.save()
        self.assertEqual(self.get(header=header).json()['count'], 0)
        self.assertEqual(self.get({'integration_id': str(self.integration.pk)}, header).json()['count'], 0)
        self.assertEqual(self.client.get('/api/v1/demographics/explorer-options/', **header).json()['integrations'], [])

    def test_multiple_sources_require_selection_and_neighborhoods_stay_distinct(self, clock):
        second = Integration.objects.create(owner=self.api_account, provider='ibge', name='Second census source')
        original = Statistic.objects.first()
        Statistic.objects.create(integration=second, geography=original.geography, category=original.category,
            value=500, last_run=self.run, fingerprint='second-source')
        self.assertEqual(self.get().status_code, 400)
        result = self.get({'integration_id': str(self.integration.pk), 'level': 'neighborhood'}).json()
        self.assertEqual(result['count'], 0)
        self.assertIn('districts', result['empty_reason'])

    def test_geographies_and_latest_coverage_are_source_scoped(self, clock):
        other = Integration.objects.create(owner=self.api_account, provider='ibge', name='No data')
        response = self.client.get('/api/v1/geographies/', {'integration_id': str(other.pk)}, **self.header)
        self.assertEqual(response.json()['count'], 0)
        DataCoverage.objects.create(run=self.run, level='district', parent_code='3550308', status='available', message='Fixture')
        self.assertEqual(self.client.get('/api/v1/ibge/coverage/', {'integration_id': str(other.pk), 'latest': 'true'}, **self.header).json()['count'], 0)
        self.assertEqual(self.client.get('/api/v1/ibge/coverage/', {'integration_id': str(self.integration.pk), 'latest': 'true'}, **self.header).json()['count'], 1)


@override_settings(SECURE_SSL_REDIRECT=False, DOCS_ENABLED=True)
class EmbeddedSwaggerTests(SimpleTestCase):
    def test_only_valid_same_origin_connection_can_embed_swagger(self):
        regular = self.client.get('/docs/')
        self.assertIn("frame-ancestors 'none'", regular['Content-Security-Policy'])
        result = self.client.get('/docs/', {'frontend_connect': 'a'*32})
        self.assertEqual(result['X-Frame-Options'], 'SAMEORIGIN')
        self.assertIn("frame-ancestors 'self'", result['Content-Security-Policy'])
        self.assertContains(result, "const connection = '"+'a'*32+"'")
        invalid = self.client.get('/docs/', {'frontend_connect': "';alert(1)//"})
        self.assertIn("frame-ancestors 'none'", invalid['Content-Security-Policy'])
        self.assertContains(invalid, "const connection = ''")
