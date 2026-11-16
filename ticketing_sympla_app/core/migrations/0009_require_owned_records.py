import uuid
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("core", "0008_seed_rbac_and_ownership")]
    # Data backfill commits before ALTER TABLE, avoiding PostgreSQL deferred-FK trigger events.
    operations = [
        migrations.AlterField(
            "apiuser",
            "identifier",
            models.UUIDField(default=uuid.uuid4, unique=True, editable=False),
        ),
        migrations.AlterField(
            "apiuser",
            "credential_identifier",
            models.UUIDField(default=uuid.uuid4, unique=True, editable=False),
        ),
        *[
            migrations.AlterField(
                name,
                "owner",
                models.ForeignKey(
                    to="core.apiuser", on_delete=django.db.models.deletion.PROTECT
                ),
            )
            for name in ["schedule", "syncrun", "event"]
        ],
    ]
