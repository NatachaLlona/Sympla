import os
import uuid
from django.db import migrations, models
import django.db.models.deletion


def seed(apps, schema_editor):
    Permission, Role, User = (
        apps.get_model("core", name) for name in ["Permission", "Role", "ApiUser"]
    )
    codes = ["read", "write", "edit", "delete"]
    for code in codes:
        Permission.objects.get_or_create(
            code=code, defaults={"description": code.capitalize() + " own data"}
        )
    roles = {}
    for name, permissions in [
        ("reader", ["read"]),
        ("operator", codes),
        ("master", codes),
    ]:
        role, _ = Role.objects.get_or_create(name=name, defaults={"is_system": True})
        role.permissions.set(permissions)
        roles[name] = role
    for user in User.objects.all():
        user.identifier, user.credential_identifier = uuid.uuid4(), uuid.uuid4()
        user.role = roles["operator" if user.can_write else "reader"]
        user.save(update_fields=["identifier", "credential_identifier", "role"])
    master = User.objects.filter(username=os.getenv("INITIAL_CLIENT_ID", "")).first()
    if master:
        master.is_superuser, master.role = True, roles["master"]
        master.save(update_fields=["is_superuser", "role"])
    for name in ["Schedule", "SyncRun", "Event"]:
        model = apps.get_model("core", name)
        rows = model.objects.filter(owner__isnull=True)
        if rows.exists() and not master:
            raise RuntimeError(
                "Legacy ownership migration requires INITIAL_CLIENT_ID from the startup configuration."
            )
        if master:
            rows.update(owner=master)
    # Historical immutable logs remain unchanged. Only the master may read unscoped legacy evidence.


class Migration(migrations.Migration):
    dependencies = [("core", "0007_accessrule_permission_role_and_more")]
    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
