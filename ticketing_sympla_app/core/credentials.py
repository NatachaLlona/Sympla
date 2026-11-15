import re
from django.contrib.auth.hashers import make_password
from django.db import transaction
from .models import ApiUser
from .services import audit
from .password_policy import PASSWORD_RULES, valid_password
from .rbac import ensure_catalog
from .models import Role
from .provider_secrets import encrypt_token


@transaction.atomic
def configure_client(
    client_id,
    client_secret,
    can_write=True,
    rotate=False,
    role=None,
    sympla_token=None,
    actor="local-administrator",
    interaction=None,
):
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,100}", client_id):
        raise ValueError(
            "Client ID must contain 3 to 100 letters, digits, dots, underscores or hyphens."
        )
    if not valid_password(client_secret):
        raise ValueError("Invalid password. " + PASSWORD_RULES)
    api_account = (
        ApiUser.objects.select_for_update().filter(client_id=client_id).first()
    )
    if api_account and not rotate:
        raise ValueError(
            "Client already exists. Use the rotate action to change its secret."
        )
    if not api_account:
        ensure_catalog()
        api_account = ApiUser(
            client_id=client_id,
            role=role or Role.objects.get(name="operator" if can_write else "reader"),
        )
    else:
        api_account.credential_version += 1
    api_account.client_secret_hash = make_password(client_secret)
    api_account.token_hash = None
    api_account.is_active, api_account.can_write = True, can_write
    if role is not None:
        api_account.role = role
    if sympla_token is not None:
        api_account.sympla_token_encrypted = encrypt_token(sympla_token)
        api_account.provider_version += 1
    api_account.save()
    audit(
        actor,
        "api_user.rotate" if rotate else "api_user.create",
        "api_user",
        api_account.pk,
        {
            "client_id": client_id,
            "active": True,
            "role_identifier": str(api_account.role.identifier),
        },
        owner=api_account,
        interaction=interaction,
    )
    return api_account
