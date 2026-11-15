from django.db import migrations


TABLES = ['core_auditlog', 'core_apirequestlog', 'core_eventversion']


def install(apps, schema_editor):
    apps.get_model('core', 'Coordinator').objects.get_or_create(pk=1)
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute('''CREATE FUNCTION sympla_protect_history() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'History is append-only'; END $$''')
        for table in TABLES:
            schema_editor.execute(f'CREATE TRIGGER protect_history BEFORE UPDATE OR DELETE ON {table} '
                                  'FOR EACH ROW EXECUTE FUNCTION sympla_protect_history()')
    elif schema_editor.connection.vendor == 'sqlite':
        for table in TABLES:
            for action in ['UPDATE', 'DELETE']:
                schema_editor.execute(f'''CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action}
                    ON {table} BEGIN SELECT RAISE(ABORT, 'History is append-only'); END''')


def uninstall(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        for table in TABLES:
            schema_editor.execute(f'DROP TRIGGER protect_history ON {table}')
        schema_editor.execute('DROP FUNCTION sympla_protect_history()')
    elif schema_editor.connection.vendor == 'sqlite':
        for table in TABLES:
            for action in ['update', 'delete']:
                schema_editor.execute(f'DROP TRIGGER {table}_no_{action}')


class Migration(migrations.Migration):
    dependencies = [('core', '0002_coordinator')]
    operations = [migrations.RunPython(install, uninstall)]
