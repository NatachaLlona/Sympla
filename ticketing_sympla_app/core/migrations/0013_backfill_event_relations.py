from django.db import migrations, models


def backfill(apps, schema_editor):
    integration_model = apps.get_model('core', 'Integration')
    api_account_model = apps.get_model('core', 'ApiUser')
    event_model = apps.get_model('core', 'Event')
    version_model = apps.get_model('core', 'EventVersion')
    observation_model = apps.get_model('core', 'EventObservation')
    for api_account in api_account_model.objects.all().iterator():
        integration = integration_model.objects.create(owner=api_account, name='Sympla', provider='sympla', is_default=True)
        for model_name in ('Event', 'Schedule', 'SyncRun'):
            apps.get_model('core', model_name).objects.filter(owner=api_account).update(integration=integration)
    apps.get_model('core', 'SyncRun').objects.update(connector_version='legacy.snapshot.v1', integration_revision=1)
    for event in event_model.objects.all().iterator():
        data = event.data
        for field in ('name', 'reference_id', 'detail', 'start_date', 'end_date', 'url', 'image'):
            value = data.get(field)
            setattr(event, field, '' if value is None else str(value))
        for field in ('published', 'cancelled', 'private_event'):
            value = data.get(field)
            setattr(event, field, bool(value) if value in (True, False, 0, 1) else None)
        versions = version_model.objects.filter(event=event).order_by('version')
        first, last = versions.first(), versions.last()
        if first:
            event.first_seen_at = first.created_at
            event.last_seen_at, event.last_run_id = last.created_at, last.run_id
        event.save()
        for key, model_name in [('address', 'EventAddress'), ('host', 'EventHost')]:
            nested = data.get(key)
            if isinstance(nested, dict) and nested:
                model = apps.get_model('core', model_name)
                allowed = {field.name for field in model._meta.fields} - {'id', 'event'}
                model.objects.create(event=event, **{key: str(value) for key, value in nested.items() if key in allowed and value is not None})
        for key, kind in [('category_prim', 'primary'), ('category_sec', 'secondary')]:
            nested = data.get(key)
            if isinstance(nested, dict) and nested:
                apps.get_model('core', 'EventCategory').objects.create(event=event, kind=kind, name=str(nested.get('name') or ''))
        for version in versions.iterator():
            import hashlib
            import json
            digest = hashlib.sha256(json.dumps(version.data, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
            observation_model.objects.create(event=event, event_version=version, run_id=version.run_id,
                collected_at=version.created_at, fingerprint=digest, transformation_version='legacy.snapshot.v1', evidence_type='legacy_version')
    permission_model = apps.get_model('core', 'Permission')
    for action in ('read', 'write', 'edit', 'delete'):
        permission_model.objects.get_or_create(code=f'integrations:{action}', defaults={'description': f'{action.title()} integrations records'})
    for role in apps.get_model('core', 'Role').objects.filter(is_system=True):
        if role.name == 'master':
            role.permissions.add(*[f'integrations:{action}' for action in ('read', 'write', 'edit', 'delete')])
        elif role.name in ('reader', 'operator'):
            role.permissions.add('integrations:read')


def protect(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute('CREATE TRIGGER protect_history BEFORE UPDATE OR DELETE ON core_eventobservation FOR EACH ROW EXECUTE FUNCTION sympla_protect_history()')
    elif schema_editor.connection.vendor == 'sqlite':
        for action in ('UPDATE', 'DELETE'):
            schema_editor.execute(f"CREATE TRIGGER core_eventobservation_no_{action.lower()} BEFORE {action} ON core_eventobservation BEGIN SELECT RAISE(ABORT, 'History is append-only'); END")


class Migration(migrations.Migration):
    dependencies = [('core', '0012_eventaddress_eventcategory_eventhost_and_more')]
    operations = [
        migrations.AddField('eventobservation', 'evidence_type', models.CharField(default='import', max_length=20)),
        migrations.RunPython(backfill),
        migrations.RunPython(protect),
    ]
