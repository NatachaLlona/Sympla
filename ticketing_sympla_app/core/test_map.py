"""Map truthfulness, locality filtering, spatial missingness and tenant isolation."""
from decimal import Decimal
from unittest.mock import patch
from django.test import TestCase
from django.db import IntegrityError, transaction
from . import test_cohorts as fixtures
from .credentials import configure_client
from .map_views import distance_km
from .models import Geography, GeographyMapReference, Statistic, StatisticalCategory, Event, EventAddress, Role


@patch('core.cohort_search.current_year', return_value=2026)
class MapApiTests(TestCase):
    token = fixtures.CohortApiTests.token

    def setUp(self):
        fixtures.CohortApiTests.setUp(self)
        for index, location in enumerate(Geography.objects.filter(level='district').order_by('code')):
            GeographyMapReference.objects.create(geography=location, latitude=-23.55, longitude=-46.63+index,
                area_km2=2, coordinate_kind='district_seat')
            Statistic.objects.create(integration=self.integration, geography=location,
                category=StatisticalCategory.objects.get(indicator_id='responsible_income_mean', code='total'),
                value=1000+index*2000, fingerprint='income-fixture', last_run=self.run)
        self.event = Event.objects.create(owner=self.api_account, integration=self.integration, external_id='map-fixture', name='Map fixture')
        EventAddress.objects.create(event=self.event, lat='-23.55', lon='-46.63')

    def get(self, extra=None, header=None):
        return self.client.get('/api/v1/demographics/map/', {'level': 'district', 'age_min': 4, 'age_max': 8, **(extra or {})}, **(header or self.header))

    def test_exact_cohort_density_uses_territorial_area(self, clock):
        response = self.get().json()
        self.assertEqual(response['count'], 3)
        first = next(row for row in response['results'] if row['exact_count'] == 100)
        self.assertEqual(first['density_lower'], 50)
        self.assertEqual(first['density_upper'], 50)
        self.assertIn('not people', response['limitations'][-4])

    def test_income_selects_localities_without_scaling_age_population(self, clock):
        body = self.get({'income_min': 2000, 'income_max': 4000}).json()
        self.assertEqual(body['count'], 1)
        self.assertEqual(body['results'][0]['exact_count'], 300)
        self.assertEqual(Decimal(body['results'][0]['income']['value']), 3000)
        self.assertEqual(body['coverage']['excluded_by_income'], 2)

    def test_event_distance_uses_owned_event_and_seat(self, clock):
        body = self.get({'event_id': self.event.pk, 'radius_km': 10}).json()
        self.assertEqual(body['count'], 1)
        self.assertEqual(body['results'][0]['distance_km'], 0)
        self.assertEqual(self.get({'radius_km': 10}).status_code, 400)
        self.assertAlmostEqual(distance_km((0,0),(0,1)), 111.195, places=2)

    def test_missing_coordinates_and_area_are_not_manufactured(self, clock):
        references = list(GeographyMapReference.objects.order_by('pk'))
        references[0].latitude = references[0].longitude = None
        references[0].save()
        references[1].area_km2 = None
        references[1].save()
        body = self.get().json()
        self.assertEqual(body['count'], 2)
        self.assertEqual(body['coverage']['missing_coordinates'], 1)
        self.assertEqual(body['coverage']['missing_area'], 1)
        self.assertTrue(any(row['density_lower'] is None for row in body['results']))

    def test_birth_gap_and_partial_bands_retain_uncertainty(self, clock):
        body = self.get({'age_min': 0, 'age_max': 3, 'estimate': 'true'}).json()
        self.assertTrue(all(row['density_upper'] is None and row['density_estimate'] is None for row in body['results']))
        body = self.get({'age_min': 6, 'age_max': 10, 'estimate': 'true'}).json()
        row = next(row for row in body['results'] if row['geography']['code'] == '355030801')
        self.assertEqual(row['estimated_count'], 140)
        self.assertEqual(row['density_estimate'], 70)

    def test_missing_income_is_excluded_only_when_filtered(self, clock):
        Statistic.objects.filter(category__indicator_id='responsible_income_mean').update(value=None, source_status='not_available')
        self.assertEqual(self.get().json()['count'], 3)
        self.assertEqual(self.get({'income_min': 0}).json()['count'], 0)

    def test_event_tenant_and_permission_boundaries(self, clock):
        other = configure_client('map-other', 'OtherPass1!')
        other.role = Role.objects.create(name='Map reader')
        other.role.permissions.set(['demographics:read'])
        other.save()
        header = self.token(other)
        self.assertEqual(self.get(header=header).json()['count'], 0)
        self.assertEqual(self.get({'event_id': self.event.pk}, header).status_code, 403)
        other.role.permissions.add('events:read')
        self.assertEqual(self.get({'event_id': self.event.pk}, header).status_code, 404)

    def test_invalid_filters_and_missing_event_coordinates(self, clock):
        for params in [{'income_min': 'NaN'}, {'income_max': '-1'}, {'income_min': 10, 'income_max': 5},
                       {'radius_km': 7000}, {'event_id': '-1'}, {'income_metric': 'salary'}, {'unexpected': 'value'}]:
            self.assertEqual(self.get(params).status_code, 400)
        EventAddress.objects.filter(event=self.event).update(lat='NaN')
        self.assertEqual(self.get({'event_id': self.event.pk, 'radius_km': 10}).status_code, 400)
        self.assertEqual(self.get({'event_id': self.event.pk}).json()['event']['coordinate_status'], 'not_available')

    def test_coordinates_must_be_paired_at_database_level(self, clock):
        ref = GeographyMapReference.objects.first()
        with self.assertRaises(IntegrityError), transaction.atomic():
            GeographyMapReference.objects.filter(pk=ref.pk).update(latitude=None)
