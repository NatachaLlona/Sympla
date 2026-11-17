"""Official scope boundaries, preset validation and collection lineage."""
from io import StringIO
from unittest.mock import patch
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase
from .integration_modules.ibge.metropolitan import catalog, municipality_codes, PRESET
from .integration_modules.ibge.connector import configuration
from .models import Integration, ImportSource, SyncRun
from . import test_ibge as ibge_fixtures


class MetropolitanCatalogTests(SimpleTestCase):
    def test_capitals_and_official_members_are_complete_and_unique(self):
        data = catalog()
        self.assertEqual(len(data['capitals']), 27)
        self.assertEqual(len({row['code'][:2] for row in data['capitals']}), 27)
        self.assertEqual(len(municipality_codes()), 430)
        self.assertTrue({row['code'] for row in data['capitals']} <= municipality_codes())
        capitals = {row['state']: row for row in data['capitals']}
        sp = capitals['SP']['areas'][0]
        self.assertEqual(len(sp['members']), 39)
        self.assertIn('3518800', sp['members'])  # Guarulhos
        self.assertNotIn('3509502', sp['members'])  # Campinas has a separate RM.
        self.assertEqual(len(capitals['MG']['areas'][0]['members']), 34)  # Excludes the separate metropolitan collar.
        self.assertIn('Integrada', capitals['DF']['areas'][0]['name'])
        self.assertTrue(any(code[:2] != '53' for code in capitals['DF']['areas'][0]['members']))
        self.assertEqual(capitals['AC']['areas'], [])
        self.assertEqual(capitals['MS']['areas'], [])
        self.assertIn('Área de Expansão Metropolitana', capitals['SC']['areas'][0]['subcategories'])

    def test_preset_is_bounded_and_cannot_silently_change_explicit_scopes(self):
        self.assertEqual(configuration({'geographic_preset': PRESET})['levels'], ['city'])
        for bad in [{'geographic_preset': 'unknown'}, {'geographic_preset': None},
                    {'geographic_preset': PRESET, 'municipality_codes': ['3550308']},
                    {'geographic_preset': PRESET, 'levels': ['neighborhood']}]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                configuration(bad)
        self.assertEqual(configuration({'municipality_codes': ['3550308']})['municipality_codes'], ['3550308'])


class MetropolitanImportTests(TestCase):
    setUp = ibge_fixtures.IbgeTests.setUp
    token = ibge_fixtures.IbgeTests.token
    download = ibge_fixtures.IbgeTests.download
    run_import = ibge_fixtures.IbgeTests.run_import
    # Reuse the tested public-source fixtures, with a deliberately narrow catalog selection.
    def test_preset_collects_municipal_data_and_preserves_distinct_source_years(self):
        self.integration.configuration = configuration({'geographic_preset': PRESET})
        self.integration.save()
        with patch('core.integration_modules.ibge.connector.municipality_codes', return_value={'3550308', '3509502'}):
            run = self.run_import()
        self.assertEqual(run.status, 'success')
        self.assertEqual(run.counts['received'], 30)
        self.assertEqual(ImportSource.objects.get(run=run, code='metropolitan_composition_2025').reference_period, '2025')
        self.assertEqual(ImportSource.objects.get(run=run, code='city_age').reference_period, '2022')

    def test_command_is_idempotent_and_preserves_existing_integration(self):
        existing_config = self.integration.configuration.copy()
        for _ in range(2):
            call_command('configure_ibge_capitals', client_id=self.api_account.client_id, stdout=StringIO())
        national = Integration.objects.get(configuration__geographic_preset=PRESET)
        self.assertEqual(SyncRun.objects.filter(integration=national).count(), 1)
        self.integration.refresh_from_db()
        self.assertEqual(self.integration.configuration, existing_config)
        self.assertNotEqual(national.pk, self.integration.pk)

    def test_command_cannot_create_scope_for_inactive_api_account(self):
        self.api_account.is_active = False
        self.api_account.save()
        with self.assertRaises(CommandError):
            call_command('configure_ibge_capitals', client_id=self.api_account.client_id, stdout=StringIO())
