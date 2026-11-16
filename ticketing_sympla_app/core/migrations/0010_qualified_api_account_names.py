from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("core", "0009_require_owned_records")]
    # Legacy SQL column names are mapped explicitly; no data, hashes or identifiers change.
    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.RenameField("apiuser", "username", "client_id"),
                migrations.AlterField(
                    "apiuser",
                    "client_id",
                    models.CharField(max_length=100, unique=True, db_column="username"),
                ),
                migrations.RenameField("accesstoken", "user", "api_account"),
                migrations.AlterField(
                    "accesstoken",
                    "api_account",
                    models.ForeignKey(
                        to="core.apiuser",
                        on_delete=django.db.models.deletion.CASCADE,
                        db_column="user_id",
                    ),
                ),
                migrations.RemoveConstraint(
                    "accessrule", "unique_individual_permission"
                ),
                migrations.RenameField("accessrule", "user", "api_account"),
                migrations.AlterField(
                    "accessrule",
                    "api_account",
                    models.ForeignKey(
                        to="core.apiuser",
                        on_delete=django.db.models.deletion.PROTECT,
                        db_column="user_id",
                    ),
                ),
                migrations.AddConstraint(
                    "accessrule",
                    models.UniqueConstraint(
                        fields=["api_account", "permission"],
                        name="unique_individual_permission",
                    ),
                ),
            ],
        )
    ]
