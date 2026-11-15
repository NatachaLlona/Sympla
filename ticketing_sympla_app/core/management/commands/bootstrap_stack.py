import os
import re
from pathlib import Path
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from psycopg import sql
from core.models import ApiUser, Role, Schedule, SyncRun, Event
from core.credentials import configure_client
from core.provider_secrets import encrypt_token, decrypt_token, ProviderSecretError
from django.conf import settings
from core.rbac import ensure_catalog


class Command(BaseCommand):
    help = "Apply migrations, configure the runtime database role, and bootstrap the API client."

    def handle(self, *args, **options):
        call_command("migrate", interactive=False, verbosity=0)
        role = os.environ["RUNTIME_DB_USER"]
        if not re.fullmatch(r"[a-z][a-z0-9_]{2,62}", role) or role in {
            "postgres",
            "sympla_admin",
        }:
            raise CommandError("Invalid runtime database account name.")
        password = Path("/run/secrets/db_password").read_text(encoding="utf-8").strip()
        client_id = os.environ["INITIAL_CLIENT_ID"]
        client_secret = (
            Path(os.environ["INITIAL_CLIENT_SECRET_FILE"])
            .read_text(encoding="utf-8")
            .strip()
        )
        rotate = os.getenv("ROTATE_INITIAL_CLIENT") == "true"
        with transaction.atomic():
            ensure_catalog()
            existing = ApiUser.objects.filter(client_id=client_id).first()
            master = ApiUser.objects.filter(is_superuser=True).first()
            if master and master.client_id != client_id:
                raise CommandError(
                    "The master client ID cannot be replaced by a different account."
                )
            if not existing or rotate:
                if not client_secret:
                    raise CommandError(
                        "API client setup is required. Run start.py --reset-api-client."
                    )
                configure_client(
                    client_id, client_secret, can_write=True, rotate=bool(existing)
                )
            master = ApiUser.objects.select_for_update().get(client_id=client_id)
            master.is_superuser, master.role = True, Role.objects.get(name="master")
            if (
                not master.sympla_token_encrypted
                or os.getenv("CONFIGURE_MASTER_PROVIDER") == "true"
            ) and settings.SYMPLA_API_KEY:
                master.sympla_token_encrypted = encrypt_token(settings.SYMPLA_API_KEY)
                master.provider_version += 1
            master.save(
                update_fields=[
                    "is_superuser",
                    "role",
                    "sympla_token_encrypted",
                    "provider_version",
                ]
            )
            try:
                for account in ApiUser.objects.exclude(
                    sympla_token_encrypted=""
                ).iterator():
                    decrypt_token(account)
            except ProviderSecretError:
                raise CommandError(
                    "Stored provider tokens cannot be decrypted. Restore the original provider encryption key."
                ) from None
                # Existing global data belongs to the original provider/master account, never to new clients.
            for model in [Schedule, SyncRun, Event]:
                model.objects.filter(owner__isnull=True).update(owner=master)
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [role])
                if not cursor.fetchone():
                    cursor.execute(
                        sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(role))
                    )
                cursor.execute(
                    sql.SQL(
                        "ALTER ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                        "NOREPLICATION PASSWORD {}"
                    ).format(sql.Identifier(role), sql.Literal(password))
                )
                cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
                cursor.execute(
                    sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                        sql.Identifier(connection.settings_dict["NAME"]),
                        sql.Identifier(role),
                    )
                )
                cursor.execute(
                    sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(
                        sql.Identifier(role)
                    )
                )
                cursor.execute(
                    sql.SQL(
                        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}"
                    ).format(sql.Identifier(role))
                )
                cursor.execute(
                    sql.SQL(
                        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}"
                    ).format(sql.Identifier(role))
                )
                cursor.execute(
                    sql.SQL(
                        "REVOKE UPDATE, DELETE ON core_auditlog, core_apirequestlog, "
                        "core_eventversion, django_migrations FROM {}"
                    ).format(sql.Identifier(role))
                )
        if not master.sympla_token_encrypted:
            self.stdout.write(
                "Warning: the master Sympla token is not configured. Use start.py --configure-sympla. Other API accounts require their own token."
            )
        self.stdout.write(
            "Database migrations, runtime role and protected master API client are ready."
        )
