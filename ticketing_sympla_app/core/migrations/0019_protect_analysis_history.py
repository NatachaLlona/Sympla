from django.db import migrations


def install(apps, schema_editor):
    permission = apps.get_model('core', 'Permission')
    codes = []
    for section in ('sales', 'scenarios', 'reports'):
        for action in ('read', 'write', 'edit', 'delete'):
            code = f'{section}:{action}'
            permission.objects.get_or_create(code=code, defaults={'description': f'{action.title()} {section} records'})
            codes.append(code)
    for role in apps.get_model('core', 'Role').objects.filter(name='master', is_system=True):
        role.permissions.add(*codes)
    for table in ('core_saleversion', 'core_scenariosnapshot'):
        if schema_editor.connection.vendor == 'postgresql':
            schema_editor.execute(f'CREATE TRIGGER protect_history BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION sympla_protect_history()')
        else:
            for action in ('UPDATE', 'DELETE'):
                schema_editor.execute(f"CREATE TRIGGER {table}_no_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'History is append-only'); END")


class Migration(migrations.Migration):
    dependencies = [('core', '0018_analysisscenario_analysisnote_salesupload_sale_and_more')]
    operations = [migrations.RunPython(install)]
