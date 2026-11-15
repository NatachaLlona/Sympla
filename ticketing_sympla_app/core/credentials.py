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
def configure_client(client_id, client_secret, can_write=True, rotate=False, role=None, sympla_token=None,
                     actor='local-administrator', interaction=None):
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,100}", client_id):
        raise ValueError(
            "Client ID must contain 3 to 100 letters, digits, dots, underscores or hyphens."
        )
    if not valid_password(client_secret):
        raise ValueError("Invalid password. " + PASSWORD_RULES)
    user = ApiUser.objects.select_for_update().filter(username=client_id).first()
    if user and not rotate:
        raise ValueError(
            "Client already exists. Use the rotate action to change its secret."
        )
    if not user:
        ensure_catalog()
        user = ApiUser(username=client_id, role=role or Role.objects.get(name='operator' if can_write else 'reader'))
    else:
        user.credential_version += 1
    user.client_secret_hash = make_password(client_secret)
    user.token_hash = None
    user.is_active, user.can_write = True, can_write
    if role is not None:
        user.role = role
    if sympla_token is not None:
        user.sympla_token_encrypted = encrypt_token(sympla_token)
        user.provider_version += 1
    user.save()
    audit(
        actor,
        "api_user.rotate" if rotate else "api_user.create",
        "api_user",
        user.pk,
        {"client_id": client_id, "active": True, "role_identifier": str(user.role.identifier)},
        owner=user,
        interaction=interaction,
    )
    return user
