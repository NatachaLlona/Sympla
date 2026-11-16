from django.db import migrations

TABLES = ('core_statisticversion', 'core_statisticobservation', 'core_importsource', 'core_datacoverage')


def install(apps, schema_editor):
    permission_model = apps.get_model('core', 'Permission')
    for action in ('read', 'write', 'edit', 'delete'):
        permission_model.objects.get_or_create(code=f'demographics:{action}', defaults={'description': f'{action.title()} demographics records'})
    for role in apps.get_model('core', 'Role').objects.filter(name='master', is_system=True):
        role.permissions.add(*[f'demographics:{action}' for action in ('read', 'write', 'edit', 'delete')])
    for table in TABLES:
        if schema_editor.connection.vendor == 'postgresql':
            schema_editor.execute(f'CREATE TRIGGER protect_history BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION sympla_protect_history()')
        elif schema_editor.connection.vendor == 'sqlite':
            for action in ('UPDATE', 'DELETE'):
                schema_editor.execute(f"CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'History is append-only'); END")


class Migration(migrations.Migration):
    dependencies = [('core', '0015_datacoverage_geography_importsource_statistic_and_more')]
    operations = [migrations.RunPython(install)]
