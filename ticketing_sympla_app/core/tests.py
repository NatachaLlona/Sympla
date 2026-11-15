import hashlib
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time, timedelta, timezone as dt_timezone
from unittest.mock import patch, MagicMock
from django.db import connection, transaction, DatabaseError, close_old_connections
from django.core.management import call_command
from io import StringIO
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from django.contrib.auth.hashers import make_password
from .models import ApiUser, AccessToken, Schedule, SyncRun, Event, EventVersion, AuditLog, ApiRequestLog, Coordinator
from .scheduling import next_occurrence
from .services import enqueue, enqueue_due, process_one, claim_run, persist_events
from .sympla import fetch_events, SyncError


class ApiTests(TestCase):
    def setUp(self):
        self.token = 'test-token-that-is-never-a-real-credential'
        self.user = ApiUser.objects.create(username='writer', can_write=True,
            client_secret_hash=make_password('Testing1!'))
        AccessToken.objects.create(user=self.user, credential_version=self.user.credential_version,
            expires_at=timezone.now() + timedelta(hours=1), token_hash=hashlib.sha256(self.token.encode()).hexdigest())
        self.headers = {'HTTP_AUTHORIZATION': 'Bearer ' + self.token}

    def post(self, path, data):
        return self.client.post(path, json.dumps(data), content_type='application/json', **self.headers)

    def test_authentication_revocation_and_readonly(self):
        self.assertEqual(self.client.get('/api/v1/schedules/').status_code, 401)
        self.user.can_write = False
        self.user.save()
        self.assertEqual(self.post('/api/v1/sync/', {}).status_code, 403)
        self.assertEqual(self.client.get('/api/v1/events/', **self.headers).status_code, 200)
        self.user.is_active = False
        self.user.save()
        self.assertEqual(self.client.get('/api/v1/events/', **self.headers).status_code, 401)
        self.assertNotIn(self.token, str(list(ApiRequestLog.objects.values())))

    def test_schedule_crud_and_validation(self):
        payload = {'time': '09:30', 'timezone': 'Europe/Lisbon', 'active': True}
        result = self.post('/api/v1/schedules/', payload)
        self.assertEqual(result.status_code, 201, result.content)
        item_id = result.json()['id']
        self.assertEqual(self.post('/api/v1/schedules/', payload).status_code, 409)
        self.assertEqual(self.post('/api/v1/schedules/', {**payload, 'time': '29:00'}).status_code, 400)
        self.assertEqual(self.post('/api/v1/schedules/', {**payload, 'timezone': 'bad-zone'}).status_code, 400)
        self.assertEqual(self.post('/api/v1/schedules/', {**payload, 'active': 'true'}).status_code, 400)
        self.assertEqual(self.post('/api/v1/schedules/', {**payload, 'unknown': 1}).status_code, 400)
        self.assertEqual(self.client.get('/api/v1/schedules/?active=true', **self.headers).json()['count'], 1)
        result = self.client.patch(f'/api/v1/schedules/{item_id}/', json.dumps({'active': False}),
                                   content_type='application/json', **self.headers)
        self.assertEqual(result.status_code, 200)
        self.assertIsNone(result.json()['next_run_at'])
        self.assertEqual(self.client.delete(f'/api/v1/schedules/{item_id}/', **self.headers).status_code, 204)
        self.assertEqual(self.client.get('/api/v1/schedules/', **self.headers).json()['count'], 0)
        self.assertEqual(AuditLog.objects.filter(resource='schedule').count(), 3)

    def test_manual_queue_and_removed_unsafe_route(self):
        self.assertEqual(self.client.get('/update/').status_code, 404)
        self.assertEqual(self.client.get('/api/v1/sync/', **self.headers).status_code, 405)
        self.assertEqual(self.post('/api/v1/sync/', {}).status_code, 202)
        self.assertEqual(self.post('/api/v1/sync/', {}).status_code, 409)
        self.assertEqual(SyncRun.objects.get().source, 'manual')
        self.assertEqual(self.client.get('/api/v1/sync-runs/', **self.headers).json()['count'], 1)

    def test_schedule_delete_cancels_only_queued(self):
        result = self.post('/api/v1/schedules/', {'time': '09:30', 'timezone': 'UTC'})
        schedule = Schedule.objects.get(pk=result.json()['id'])
        with transaction.atomic():
            run = enqueue('scheduler', source='scheduled', schedule=schedule, scheduled_for=timezone.now())
        self.client.delete(f'/api/v1/schedules/{schedule.pk}/', **self.headers)
        run.refresh_from_db()
        self.assertEqual(run.status, 'cancelled')

    def test_business_and_audit_rollback_together(self):
        with patch('core.views.audit', side_effect=RuntimeError('secret-do-not-expose')):
            result = self.post('/api/v1/schedules/', {'time': '09:30', 'timezone': 'UTC'})
        self.assertEqual(result.status_code, 500)
        self.assertNotIn(b'secret-do-not-expose', result.content)
        self.assertFalse(Schedule.objects.exists())
        self.assertEqual(ApiRequestLog.objects.get().http_status, 500)

    def test_audit_readonly_and_pagination(self):
        self.assertEqual(self.post('/api/v1/audit-logs/', {}).status_code, 405)
        self.assertEqual(self.client.get('/api/v1/events/?page_size=1000', **self.headers).status_code, 400)
        self.assertEqual(self.client.get('/api/v1/events/999/versions/', **self.headers).status_code, 404)

    @patch('core.services.fetch_events', return_value=[{'id': 'integration-event', 'name': 'Imported'}])
    def test_api_to_worker_to_history(self, fetch):
        self.assertEqual(self.post('/api/v1/sync/', {}).status_code, 202)
        # TestCase owns a transaction; a real worker owns its own connection/process.
        with patch('core.management.commands.sync_worker.close_old_connections'):
            call_command('sync_worker', once=True, stdout=StringIO())
        result = self.client.get('/api/v1/events/', **self.headers).json()['results'][0]
        self.assertEqual(result['data']['name'], 'Imported')
        history = self.client.get(f"/api/v1/events/{result['id']}/versions/", **self.headers).json()
        self.assertEqual(history['count'], 1)
        self.assertEqual(self.client.get('/api/v1/audit-logs/?resource=event', **self.headers).json()['count'], 1)

    def test_user_rotation_and_revocation_commands(self):
        output = StringIO()
        with patch('core.management.commands.api_user.getpass.getpass', return_value='Testing1!'):
            call_command('api_user', 'create', 'command-user', write=True, stdout=output)
        original = self.client.post('/api/v1/token/', {'grant_type': 'client_credentials',
            'client_id': 'command-user', 'client_secret': 'Testing1!'}, content_type='application/json').json()['access_token']
        output = StringIO()
        with patch('core.management.commands.api_user.getpass.getpass', return_value='Rotated1!'):
            call_command('api_user', 'rotate', 'command-user', stdout=output)
        replacement = self.client.post('/api/v1/token/', {'grant_type': 'client_credentials',
            'client_id': 'command-user', 'client_secret': 'Rotated1!'}, content_type='application/json').json()['access_token']
        self.assertNotEqual(original, replacement)
        self.assertEqual(self.client.get('/api/v1/events/', HTTP_AUTHORIZATION='Bearer ' + original).status_code, 401)
        self.assertEqual(self.client.get('/api/v1/events/', HTTP_AUTHORIZATION='Bearer ' + replacement).status_code, 200)
        call_command('api_user', 'revoke', 'command-user', stdout=StringIO())
        self.assertEqual(self.client.get('/api/v1/events/', HTTP_AUTHORIZATION='Bearer ' + replacement).status_code, 401)
        self.assertNotIn(replacement, str(list(AuditLog.objects.values())))

    def test_scheduled_job_does_not_block_manual_queue(self):
        enqueue('scheduler', source='scheduled')
        self.assertEqual(self.post('/api/v1/sync/', {}).status_code, 202)

    def test_oversized_request_is_rejected(self):
        result = self.post('/api/v1/schedules/', {'padding': 'x' * 5000})
        self.assertEqual(result.status_code, 413)


class SyncTests(TestCase):
    def queue(self):
        return enqueue('tester')

    @patch('core.services.fetch_events')
    def test_versioning_and_nested_differences(self, fetch):
        fetch.return_value = [{'id': 'opaque-id', 'name': 'First', 'address': {'city': 'Lisbon'}, 'token': 'omit'}]
        self.queue()
        run = process_one()
        self.assertEqual(run.status, 'success')
        self.assertEqual(Event.objects.get().version, 1)
        self.assertNotIn('token', Event.objects.get().data)
        self.queue()
        self.assertEqual(process_one().counts['unchanged'], 1)
        self.assertEqual(EventVersion.objects.count(), 1)
        fetch.return_value = [{'id': 'opaque-id', 'name': 'Second', 'address': {'city': 'Porto'}}]
        self.queue()
        process_one()
        version = EventVersion.objects.get(version=2)
        self.assertEqual(version.differences['/address/city']['before'], 'Lisbon')
        self.assertEqual(version.differences['/address/city']['after'], 'Porto')
        self.assertEqual(AuditLog.objects.filter(action='event.updated').count(), 1)

    @patch('core.services.fetch_events')
    def test_failure_rolls_back_all_events_and_logs_failure(self, fetch):
        fetch.return_value = [{'id': 'valid', 'name': 'valid'}, {'id': 'invalid', 'name': {'bad': 'shape'}}]
        self.queue()
        run = process_one()
        self.assertEqual(run.status, 'failed')
        self.assertFalse(Event.objects.exists())
        self.assertFalse(EventVersion.objects.exists())
        self.assertFalse(AuditLog.objects.filter(resource='event').exists())
        self.assertTrue(AuditLog.objects.filter(action='sync.failed').exists())
        self.assertIsNone(run.running_slot)

    @patch('core.services.fetch_events', side_effect=SyncError('upstream_http_error'))
    def test_upstream_failure_preserves_existing_events(self, fetch):
        Event.objects.create(external_id='existing', data={'id': 'existing'}, version=1)
        self.queue()
        self.assertEqual(process_one().error_code, 'upstream_http_error')
        self.assertEqual(Event.objects.count(), 1)

    def test_only_one_running_job(self):
        self.queue()
        self.queue()
        self.assertIsNotNone(claim_run())
        self.assertIsNone(claim_run())

    def test_due_once_inactive_ignored_and_downtime_coalesced(self):
        now = timezone.now()
        schedule = Schedule.objects.create(time=time(9), timezone='UTC', active=True,
                  next_run_at=now-timedelta(days=3), created_by='tester')
        Schedule.objects.create(time=time(10), timezone='UTC', active=False,
                  next_run_at=now-timedelta(days=3), created_by='tester')
        self.assertEqual(enqueue_due(now), 1)
        self.assertEqual(enqueue_due(now), 0)
        self.assertEqual(SyncRun.objects.count(), 1)
        schedule.refresh_from_db()
        self.assertGreater(schedule.next_run_at, now)

    def test_dst_gap_and_fold(self):
        after = datetime(2026, 3, 29, 0, tzinfo=dt_timezone.utc)
        self.assertEqual(next_occurrence(time(1, 30), 'Europe/Lisbon', after).date().isoformat(), '2026-03-30')
        after = datetime(2026, 10, 25, 0, tzinfo=dt_timezone.utc)
        first = next_occurrence(time(1, 30), 'Europe/Lisbon', after)
        self.assertEqual(first.hour, 0)
        self.assertEqual(next_occurrence(time(1, 30), 'Europe/Lisbon', first).date().isoformat(), '2026-10-26')

    def test_history_is_append_only_at_database_level(self):
        log = AuditLog.objects.create(interaction_id=uuid.uuid4(), actor='a', action='a', resource='a', target_id='1')
        for operation in [lambda: AuditLog.objects.filter(pk=log.pk).update(actor='bad'),
                          lambda: AuditLog.objects.filter(pk=log.pk).delete()]:
            with self.assertRaises(DatabaseError), transaction.atomic():
                operation()


@override_settings(SYMPLA_API_HOST='https://api.sympla.com.br/public/v1.6.0', SYMPLA_API_KEY='test-not-real')
class FetchTests(TestCase):
    def response(self, data, status=200):
        response = MagicMock()
        response.status_code = status
        response.iter_content.return_value = [json.dumps(data).encode()]
        response.__enter__.return_value = response
        return response

    @patch('core.sympla.requests.Session')
    def test_has_next_does_not_use_quantity_as_total(self, session):
        client = session.return_value.__enter__.return_value
        client.get.side_effect = [self.response({'data': [{'id': '1'}], 'pagination': {'quantity': 1, 'has_next': True}}),
                                  self.response({'data': [{'id': '2'}], 'pagination': {'quantity': 1, 'has_next': False}})]
        self.assertEqual(len(fetch_events()), 2)
        self.assertFalse(client.get.call_args.kwargs['allow_redirects'])

    @patch('core.sympla.requests.Session')
    def test_cursor_pagination(self, session):
        client = session.return_value.__enter__.return_value
        client.get.side_effect = [self.response({'data': [{'id': '1'}], 'pagination': {'next_cursor': 'next'}}),
                                  self.response({'data': [{'id': '2'}], 'pagination': {'next_cursor': None}})]
        self.assertEqual(len(fetch_events()), 2)
        self.assertEqual(client.get.call_args.kwargs['params']['cursor'], 'next')

    @patch('core.sympla.requests.Session')
    def test_invalid_pagination_redirect_and_duplicates(self, session):
        client = session.return_value.__enter__.return_value
        for response in [self.response({}, 302), self.response({'data': [], 'pagination': {'has_next': True}}),
                         self.response({'data': [{'id': '1'}, {'id': '1'}], 'pagination': {'has_next': False}})]:
            client.get.side_effect = None
            client.get.return_value = response
            with self.assertRaises(SyncError):
                fetch_events()

    @override_settings(SYMPLA_API_HOST='https://attacker.example')
    @patch('core.sympla.requests.Session')
    def test_disallowed_host_never_receives_token(self, session):
        with self.assertRaises(SyncError):
            fetch_events()
        session.assert_not_called()


class PostgresConcurrencyTests(TransactionTestCase):
    def setUp(self):
        if connection.vendor != 'postgresql':
            self.skipTest('Real row locks require PostgreSQL')
        Coordinator.objects.get_or_create(pk=1)

    def test_two_workers_claim_only_one_global_slot(self):
        with transaction.atomic():
            enqueue('one')
            enqueue('two')
        def claim():
            close_old_connections()
            try:
                run = claim_run()
                return str(run.pk) if run else None
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: claim(), range(2)))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(SyncRun.objects.filter(status='running').count(), 1)

    def test_two_schedulers_enqueue_only_one_occurrence(self):
        now = timezone.now()
        Schedule.objects.create(time=time(9), timezone='UTC', active=True,
            next_run_at=now-timedelta(minutes=1), created_by='tester')
        def tick():
            close_old_connections()
            try:
                return enqueue_due(now)
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: tick(), range(2)))
        self.assertEqual(sorted(results), [0, 1])
        self.assertEqual(SyncRun.objects.count(), 1)
