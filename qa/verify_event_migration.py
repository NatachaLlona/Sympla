"""Exercise a populated legacy schema upgrade in an owned, temporary QA database."""
import os
from pathlib import Path
import sys
import uuid
from datetime import time
import psycopg
from psycopg import sql


def main():
    database_name = 'sympla_migration_qa_' + uuid.uuid4().hex[:12]
    assert database_name.startswith('sympla_migration_qa_') and len(database_name) == 32
    admin = psycopg.connect(host=os.environ['TEST_POSTGRES_HOST'], port=os.getenv('TEST_POSTGRES_PORT', '55439'),
        dbname='postgres', user='sympla_qa', password='disposable-local-qa-only', autocommit=True)
    admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(database_name)))
    try:
        os.environ['TEST_POSTGRES_NAME'] = database_name
        os.environ['DJANGO_SETTINGS_MODULE'] = 'ticketing_sympla_app.test_settings'
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ticketing_sympla_app'))
        import django
        django.setup()
        from django.db import connection, transaction, DatabaseError
        from django.db.migrations.executor import MigrationExecutor
        from django.utils import timezone
        executor = MigrationExecutor(connection)
        old_target = [('core', '0011_scoped_permissions')]
        executor.migrate(old_target)
        old = executor.loader.project_state(old_target).apps
        api_account = old.get_model('core', 'ApiUser').objects.create(client_id='migration-fixture', client_secret_hash='fixture-preserved-hash', credential_version=7)
        run = old.get_model('core', 'SyncRun').objects.create(id=uuid.uuid4(), owner=api_account, source='manual', actor='migration-fixture', status='success')
        schedule = old.get_model('core', 'Schedule').objects.create(owner=api_account, time=time(10), timezone='UTC', next_run_at=timezone.now(), created_by='migration-fixture')
        first_data = {'id': 'legacy-1', 'name': 'First', 'address': {'city': 'Lisbon'}}
        final_data = {'id': 'legacy-1', 'name': 'Current', 'published': True, 'address': {'city': 'Porto'}, 'host': {'name': 'Host'}, 'category_prim': {'name': 'Business'}}
        event = old.get_model('core', 'Event').objects.create(owner=api_account, external_id='legacy-1', version=2, data=final_data)
        version_model = old.get_model('core', 'EventVersion')
        for number, data in enumerate((first_data, final_data), 1):
            version_run = run if number == 1 else old.get_model('core', 'SyncRun').objects.create(
                id=uuid.uuid4(), owner=api_account, source='manual', actor='migration-fixture', status='success')
            version_model.objects.create(event=event, run=version_run, version=number, data=data, differences={})
        before = list(version_model.objects.values('id', 'event_id', 'version', 'data', 'differences', 'run_id', 'created_at'))
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        from core.models import ApiUser, Event, Schedule, SyncRun, EventVersion, EventObservation, Integration
        after = list(EventVersion.objects.values('id', 'event_id', 'version', 'data', 'differences', 'run_id', 'created_at'))
        assert before == after
        stored = ApiUser.objects.get(pk=api_account.pk)
        assert (stored.client_secret_hash, stored.credential_version) == ('fixture-preserved-hash', 7)
        stored = Event.objects.get(pk=event.pk)
        assert stored.name == 'Current' and stored.address.city == 'Porto' and stored.host.name == 'Host'
        assert stored.categories.get().name == 'Business' and stored.data == final_data
        assert Schedule.objects.get(pk=schedule.pk).integration_id == stored.integration_id
        assert SyncRun.objects.get(pk=run.pk).integration_id == stored.integration_id
        assert Integration.objects.get().owner_id == api_account.pk
        assert EventObservation.objects.count() == 2
        assert set(EventObservation.objects.values_list('evidence_type', flat=True)) == {'legacy_version'}
        assert stored.first_seen_at == before[0]['created_at'] and stored.last_seen_at == before[1]['created_at']
        try:
            with transaction.atomic():
                EventObservation.objects.update(fingerprint='forbidden')
        except DatabaseError:
            pass
        else:
            raise AssertionError('The immutable observation trigger is missing.')
        connection.close()
        print('PASS: populated PostgreSQL migration preserves credentials and immutable versions, projects relations, links schedules/runs and labels historical lineage.')
    finally:
        admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(database_name)))
        admin.close()


if __name__ == '__main__':
    main()
