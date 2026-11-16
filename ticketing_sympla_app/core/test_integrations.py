import hashlib
import json
from datetime import timedelta
from unittest.mock import patch
from django.db import DatabaseError, transaction
from django.test import TestCase
from django.utils import timezone
from .credentials import configure_client
from .models import (AccessToken, Role, Integration, Event, EventVersion, EventObservation,
                     EventAddress, EventCategory, Schedule, SyncRun, AuditLog)
from .services import enqueue, process_one, enqueue_due
from .integrations import default_integration
from .connectors import CONNECTORS


class IntegrationTests(TestCase):
    def setUp(self):
        self.master = configure_client('integration-master', 'MasterPass1!', sympla_token='isolated-provider-secret')
        self.master.is_superuser = True
        self.master.save()
        self.integration = default_integration(self.master)
        self.master_header = self.header(self.master)

    def header(self, api_account):
        value = f'integration-test-{api_account.identifier}'
        AccessToken.objects.update_or_create(token_hash=hashlib.sha256(value.encode()).hexdigest(), defaults={
            'api_account': api_account, 'credential_version': api_account.credential_version,
            'expires_at': timezone.now() + timedelta(hours=1),
        })
        return {'HTTP_AUTHORIZATION': 'Bearer ' + value}

    def request(self, method, path, data=None, header=None):
        return getattr(self.client, method)(path, data=json.dumps(data) if data is not None else '',
            content_type='application/json', **(header or self.master_header))

    def create_integration(self, **fields):
        result = self.request('post', '/api/v1/integrations/', {'name': 'Second source', 'provider': 'sympla', **fields})
        self.assertEqual(result.status_code, 201, result.content)
        return Integration.objects.get(pk=result.json()['id'])

    @patch('core.connectors.fetch_events')
    def test_relational_projection_versions_and_unchanged_lineage(self, fetch):
        payload = {'id': 'event-1', 'name': 'Conference', 'start_date': '2026-12-01 09:00:00',
                   'published': True, 'address': {'city': 'Lisbon', 'country': 'Portugal'},
                   'host': {'name': 'Organizer'}, 'category_prim': {'name': 'Business'},
                   'category_sec': {'name': 'Technology'}, 'token': 'never-store-this'}
        fetch.return_value = [payload]
        enqueue('tester', owner=self.master)
        first = process_one()
        event = Event.objects.get()
        self.assertEqual(event.name, 'Conference')
        self.assertEqual(event.address.city, 'Lisbon')
        self.assertEqual(event.host.name, 'Organizer')
        self.assertEqual(event.categories.count(), 2)
        self.assertEqual(event.integration_id, self.integration.pk)
        self.assertNotIn('token', event.data)
        self.assertEqual(event.start_date, payload['start_date'])
        enqueue('tester', owner=self.master)
        second = process_one()
        self.assertEqual(second.counts['unchanged'], 1)
        self.assertEqual(EventVersion.objects.count(), 1)
        self.assertEqual(EventObservation.objects.count(), 2)
        event.refresh_from_db()
        self.assertEqual(event.last_run_id, second.pk)
        self.assertEqual(event.last_seen_at, second.collected_at)
        self.assertLessEqual(event.first_seen_at, first.collected_at)
        fetch.return_value = [{'id': 'event-1', 'name': 'Changed', 'address': {'city': 'Porto'}}]
        enqueue('tester', owner=self.master)
        process_one()
        event.refresh_from_db()
        self.assertEqual(event.version, 2)
        self.assertEqual(event.name, 'Changed')
        self.assertEqual(event.address.city, 'Porto')
        self.assertEqual(EventCategory.objects.count(), 0)
        self.assertEqual(EventObservation.objects.count(), 3)
        lineage = self.request('get', f'/api/v1/events/{event.pk}/observations/').json()
        self.assertEqual(lineage['count'], 3)
        self.assertEqual(lineage['results'][0]['transformation_version'], 'sympla.events.v1')
        self.assertEqual(lineage['results'][0]['evidence_type'], 'import')
        response = self.request('get', f'/api/v1/events/{event.pk}/').json()
        self.assertEqual(response['address']['city'], 'Porto')
        self.assertNotIn('isolated-provider-secret', json.dumps(response))

    @patch('core.connectors.fetch_events', return_value=[{'id': 'same-id', 'name': 'An event'}])
    def test_sources_have_independent_external_identifiers(self, fetch):
        second = self.create_integration()
        for integration in (self.integration, second):
            enqueue('tester', owner=self.master, integration=integration)
            self.assertEqual(process_one().status, 'success')
        self.assertEqual(Event.objects.count(), 2)
        result = self.request('get', f'/api/v1/events/?integration_id={second.pk}').json()
        self.assertEqual(result['count'], 1)
        self.assertEqual(result['results'][0]['integration_id'], str(second.pk))

    def test_integration_crud_owner_isolation_and_provider_validation(self):
        second = self.create_integration(is_default=True)
        self.assertEqual(default_integration(self.master).pk, second.pk)
        self.assertEqual(self.request('patch', f'/api/v1/integrations/{second.pk}/', {'name': 'Renamed'}).status_code, 200)
        self.assertEqual(self.request('post', '/api/v1/integrations/', {'name': 'Bad', 'provider': 'https://localhost'}).status_code, 400)
        self.assertEqual(self.request('patch', f'/api/v1/integrations/{second.pk}/', {'provider': 'other'}).status_code, 400)
        foreign = configure_client('foreign-client', 'ForeignPass1!', sympla_token='foreign-token')
        header = self.header(foreign)
        # Grant only the owned integration operations for this test.
        foreign.role = Role.objects.create(name='Integration operator')
        foreign.role.permissions.set([f'integrations:{action}' for action in ('read', 'write', 'edit', 'delete')] + ['synchronization:write', 'schedules:write'])
        foreign.save()
        for method in ('get', 'patch', 'delete'):
            self.assertEqual(self.request(method, f'/api/v1/integrations/{second.pk}/', {'active': False} if method == 'patch' else None, header).status_code, 404)
        self.assertEqual(self.request('post', '/api/v1/sync/', {'integration_id': str(second.pk)}, header).status_code, 404)
        self.assertEqual(self.request('post', '/api/v1/schedules/', {'time': '10:00', 'timezone': 'UTC', 'integration_id': str(second.pk)}, header).status_code, 404)

    def test_each_crud_permission_is_independent(self):
        api_account = configure_client('crud-client', 'ClientPass1!', sympla_token='test-token')
        role = Role.objects.create(name='One action')
        api_account.role = role
        api_account.save()
        integration = default_integration(api_account)
        for action in ('read', 'write', 'edit', 'delete'):
            role.permissions.set([f'integrations:{action}'])
            header = self.header(api_account)
            path = f'/api/v1/integrations/{integration.pk}/'
            self.assertEqual(self.request('get', path, header=header).status_code, 200 if action == 'read' else 403)
            self.assertEqual(self.request('post', '/api/v1/integrations/', {'name': 'Created ' + action, 'provider': 'sympla'}, header).status_code, 201 if action == 'write' else 403)
            self.assertEqual(self.request('patch', path, {'name': 'Updated'}, header).status_code, 200 if action == 'edit' else 403)
            self.assertEqual(self.request('delete', path, header=header).status_code, 204 if action == 'delete' else 403)

    @patch('core.connectors.fetch_events', return_value=[{'id': 'kept', 'name': 'Preserved'}])
    def test_soft_delete_preserves_history_and_cancels_work(self, fetch):
        enqueue('tester', owner=self.master)
        process_one()
        result = self.request('post', '/api/v1/schedules/', {'time': '10:00', 'timezone': 'UTC'})
        self.assertEqual(result.status_code, 201)
        queued = enqueue('tester', owner=self.master)
        self.assertEqual(self.request('delete', f'/api/v1/integrations/{self.integration.pk}/').status_code, 204)
        queued.refresh_from_db()
        self.assertEqual(queued.status, 'cancelled')
        self.assertFalse(Schedule.objects.get().active)
        self.assertEqual(Event.objects.count(), 1)
        self.assertEqual(EventObservation.objects.count(), 1)
        self.assertEqual(self.request('get', '/api/v1/events/').status_code, 200)
        self.assertEqual(self.request('post', '/api/v1/sync/', {}).status_code, 409)
        self.assertTrue(AuditLog.objects.filter(action='integration.deleted').exists())

    @patch('core.connectors.fetch_events')
    def test_integration_change_during_collection_rolls_back(self, fetch):
        def collect(**kwargs):
            Integration.objects.filter(pk=self.integration.pk).update(active=False, revision=2)
            return [{'id': 'stale', 'name': 'Must not commit'}]
        fetch.side_effect = collect
        enqueue('tester', owner=self.master)
        self.assertEqual(process_one().error_code, 'integration_changed')
        self.assertFalse(Event.objects.exists())
        self.assertFalse(EventObservation.objects.exists())

    @patch('core.connectors.fetch_events', return_value=[{'id': 'valid', 'address': {'city': 'Lisbon'}}, {'id': 'invalid', 'published': 'invalid'}])
    def test_relations_and_observations_rollback_together(self, fetch):
        enqueue('tester', owner=self.master)
        self.assertEqual(process_one().error_code, 'upstream_invalid_event')
        for model in (Event, EventAddress, EventVersion, EventObservation):
            self.assertFalse(model.objects.exists())

    @patch('core.connectors.fetch_events', return_value=[{'id': 'immutable'}])
    def test_observation_history_is_append_only(self, fetch):
        enqueue('tester', owner=self.master)
        process_one()
        for mutate in (lambda: EventObservation.objects.update(fingerprint='changed'), lambda: EventObservation.objects.all().delete()):
            with self.assertRaises(DatabaseError), transaction.atomic():
                mutate()

    def test_schedules_use_selected_integration(self):
        second = self.create_integration()
        for integration in (self.integration, second):
            result = self.request('post', '/api/v1/schedules/', {'time': '10:00', 'timezone': 'UTC', 'integration_id': str(integration.pk)})
            self.assertEqual(result.status_code, 201)
        Schedule.objects.update(next_run_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(enqueue_due(), 2)
        self.assertEqual(set(SyncRun.objects.values_list('integration_id', flat=True)), {self.integration.pk, second.pk})

    def test_registered_connector_contract_supports_another_source(self):
        class FixtureConnector:
            code = 'fixture'
            version = 'fixture.events.v1'
            credential_scope = 'api_account'
            def configuration_error(self, integration, api_account):
                return None
            def collect(self, integration, api_account):
                return [{'source_id': 'fixture-1', 'title': 'Another provider'}]
            def normalize(self, payload):
                return {'id': payload['source_id'], 'name': payload['title']}
        with patch.dict(CONNECTORS, fixture=FixtureConnector()):
            result = self.request('post', '/api/v1/integrations/', {'name': 'Future provider', 'provider': 'fixture'})
            self.assertEqual(result.status_code, 201)
            integration = Integration.objects.get(pk=result.json()['id'])
            enqueue('tester', owner=self.master, integration=integration)
            run = process_one()
            self.assertEqual(run.status, 'success')
            self.assertEqual(run.connector_version, 'fixture.events.v1')
            self.assertEqual(Event.objects.get().name, 'Another provider')
