import getpass
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from core.models import ApiUser
from core.credentials import configure_client
from core.services import audit


class Command(BaseCommand):
    help = "Create, rotate or revoke API client credentials. Obtain access tokens from POST /api/v1/token/."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["create", "rotate", "revoke"])
        parser.add_argument("username", help="The API username is the client ID")
        parser.add_argument("--write", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        name, action = options["username"], options["action"]
        user = ApiUser.objects.select_for_update().filter(username=name).first()
        if action != "create" and not user:
            raise CommandError("Client not found")
        if action == "revoke":
            user.is_active = False
            user.credential_version += 1
            user.save(update_fields=["is_active", "credential_version"])
            audit(
                "local-administrator",
                "api_user.revoke",
                "api_user",
                user.pk,
                {"client_id": name, "active": False},
            )
            self.stdout.write("Client revoked. Existing access tokens are invalid.")
            return
        if action == "create" and user:
            raise CommandError("Client already exists; rotate instead")
        secret = getpass.getpass("Client secret: ")
        if getpass.getpass("Confirm client secret: ") != secret:
            raise CommandError("Client secrets do not match.")
        try:
            configure_client(
                name,
                secret,
                can_write=user.can_write if user else options["write"],
                rotate=(action == "rotate"),
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from None
        self.stdout.write(
            "Client credentials saved. Obtain a token from POST /api/v1/token/."
        )
