from django.db import migrations, models


def seed(apps, schema_editor):
    permission_model = apps.get_model('core', 'Permission')
    role_model = apps.get_model('core', 'Role')
    rule_model = apps.get_model('core', 'AccessRule')
    sections = ('identity', 'roles', 'authorization', 'schedules', 'synchronization', 'events', 'audit')
    actions = ('read', 'write', 'edit', 'delete')
    codes = [f'{section}:{action}' for section in sections for action in actions]
    legacy = {
        'read': [f'{section}:read' for section in ('schedules', 'synchronization', 'events', 'audit')],
        'write': ['schedules:write', 'synchronization:write'],
        'edit': ['schedules:edit'],
        'delete': ['schedules:delete'],
    }
    for code in codes:
        section, action = code.split(':')
        permission_model.objects.get_or_create(code=code, defaults={'description': f'{action.title()} {section} records'})
    for role in role_model.objects.all():
        previous = list(role.permissions.values_list('code', flat=True))
        expanded = {value for code in previous for value in legacy.get(code, [code])}
        if role.name == 'master' and role.is_system:
            expanded = set(codes)
        role.permissions.set(expanded)
    for rule in list(rule_model.objects.filter(permission_id__in=legacy)):
        for code in legacy[rule.permission_id]:
            rule_model.objects.get_or_create(api_account_id=rule.api_account_id, permission_id=code)
        rule.delete()
    permission_model.objects.filter(code__in=legacy).delete()


class Migration(migrations.Migration):
    dependencies = [('core', '0010_qualified_api_account_names')]
    operations = [
        migrations.AlterField('permission', 'code', models.CharField(max_length=64, primary_key=True, serialize=False)),
        migrations.RunPython(seed),
    ]
