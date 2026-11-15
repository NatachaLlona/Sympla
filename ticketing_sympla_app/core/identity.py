"""Master-only identity/RBAC administration; provider credentials are write-only."""

import json
import secrets
import string
import uuid
from django.contrib.auth.hashers import make_password
from django.db.models import F
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from .api_errors import ApiProblem
from .auth import api_endpoint
from .models import ApiUser, Role, Permission, AccessRule, SyncRun, AccessToken
from .rbac import PERMISSIONS, effective_permissions
from .credentials import configure_client
from .provider_secrets import encrypt_token
from .services import audit


def payload(request, allowed, required=()):
    try:
        if request.content_type != "application/json" or len(request.body) > 4096:
            raise ValueError()
        data = json.loads(request.body)
        if (
            not isinstance(data, dict)
            or data.keys() - set(allowed)
            or set(required) - data.keys()
        ):
            raise ValueError()
        return data
    except (ValueError, TypeError):
        raise ApiProblem(
            "invalid_request", "Provide a JSON object with the documented fields."
        ) from None


def identifier(value):
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        raise ApiProblem(
            "invalid_identifier", "A UUID identifier is required."
        ) from None


def target_user(value):
    user = (
        ApiUser.objects.select_for_update()
        .filter(identifier=value, deleted_at__isnull=True)
        .first()
    )
    if not user:
        raise ApiProblem("not_found", "API user not found.", 404)
    return user


def ordinary(user):
    if user.is_superuser:
        raise ApiProblem(
            "protected_master",
            "The bootstrap master identity is protected. Use the terminal for credential changes.",
            403,
        )


def role_for(value):
    role = Role.objects.filter(identifier=identifier(value)).first()
    if not role:
        raise ApiProblem("not_found", "Role not found.", 404)
    if role.name == "master":
        raise ApiProblem(
            "protected_role", "The master role cannot be assigned through the API.", 403
        )
    return role


def permission_codes(values):
    if (
        not isinstance(values, list)
        or any(not isinstance(v, str) or v not in PERMISSIONS for v in values)
        or len(set(values)) != len(values)
    ):
        raise ApiProblem(
            "invalid_permissions",
            "Permissions must be a unique list containing only read, write, edit and delete.",
        )
    return values


def user_data(user):
    return {
        "identifier": str(user.identifier),
        "client_id": user.username,
        "role_identifier": str(user.role.identifier) if user.role else None,
        "role": user.role.name if user.role else None,
        "is_superuser": user.is_superuser,
        "is_active": user.is_active,
        "created_at": user.created_at,
        "permissions": sorted(effective_permissions(user)),
        "role_permissions": (
            sorted(user.role.permissions.values_list("code", flat=True))
            if user.role_id
            else []
        ),
        "individual_permissions": sorted(
            AccessRule.objects.filter(user=user).values_list("permission_id", flat=True)
        ),
        "sympla_token_configured": bool(user.sympla_token_encrypted),
        "credential_identifier": str(user.credential_identifier),
        "credentials_active": bool(user.client_secret_hash),
    }


def role_data(role):
    return {
        "identifier": str(role.identifier),
        "name": role.name,
        "description": role.description,
        "is_system": role.is_system,
        "permissions": sorted(role.permissions.values_list("code", flat=True)),
    }


def collection(request, rows, serializer):
    try:
        number, size = int(request.GET.get("page", "1")), int(
            request.GET.get("page_size", "50")
        )
        if not 1 <= number <= 100000 or not 1 <= size <= 100:
            raise ValueError()
    except ValueError:
        raise ApiProblem(
            "invalid_pagination", "Use page >= 1 and page_size between 1 and 100."
        ) from None
    return JsonResponse(
        {
            "count": rows.count(),
            "page": number,
            "page_size": size,
            "results": [
                serializer(row) for row in rows[(number - 1) * size : number * size]
            ],
        }
    )


def record(request, action, resource, target, changes=None, owner=None):
    audit(
        request.api_user.username,
        action,
        resource,
        target,
        changes,
        request.interaction_id,
        owner=owner or request.api_user,
    )


def cancel_queued(request, user):
    for run in SyncRun.objects.select_for_update().filter(owner=user, status="queued"):
        run.status, run.finished_at = "cancelled", timezone.now()
        run.save(update_fields=["status", "finished_at"])
        record(request, "sync.cancelled", "sync_run", run.pk, owner=user)


def new_secret():
    chars = [
        secrets.choice(group)
        for group in [
            string.ascii_uppercase,
            string.ascii_lowercase,
            string.digits,
            "!@#$%*-_",
        ]
    ]
    chars += [
        secrets.choice(string.ascii_letters + string.digits + "!@#$%*-_")
        for _ in range(12)
    ]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


@api_endpoint(["GET"], identity=True)
def me(request):
    return JsonResponse(user_data(request.api_user))


@api_endpoint(["GET", "POST"], master=True, identity=True)
def users(request):
    if request.method == "GET":
        return collection(
            request,
            ApiUser.objects.filter(deleted_at__isnull=True).order_by("id"),
            user_data,
        )
    data = payload(
        request,
        ["client_id", "role_identifier", "sympla_token", "client_secret"],
        ["client_id", "role_identifier", "sympla_token"],
    )
    role = role_for(data["role_identifier"])
    secret = data["client_secret"] if "client_secret" in data else new_secret()
    try:
        user = configure_client(
            data["client_id"],
            secret,
            role=role,
            sympla_token=data["sympla_token"],
            actor=request.api_user.username,
            interaction=request.interaction_id,
        )
    except (ValueError, TypeError):
        raise ApiProblem(
            "invalid_credentials",
            "Use a valid client ID, an 8-16 character client secret with uppercase/lowercase/digit/special, and a nonempty Sympla token.",
        ) from None
    record(
        request,
        "identity.created",
        "api_user",
        user.identifier,
        {"client_id": user.username, "role_identifier": str(role.identifier)},
        owner=user,
    )
    return JsonResponse(
        {
            **user_data(user),
            "client_secret": secret,
            "message": "Store this client secret securely; it is returned only once.",
        },
        status=201,
    )


@api_endpoint(["GET", "PATCH", "DELETE"], identity=True)
def user_detail(request, user_identifier):
    user = target_user(user_identifier)
    if not request.api_user.is_superuser and user.pk != request.api_user.pk:
        raise ApiProblem("not_found", "API user not found.", 404)
    if request.method == "GET":
        return JsonResponse(user_data(user))
    if not request.api_user.is_superuser:
        raise ApiProblem(
            "forbidden", "Master authority is required to change identity status.", 403
        )
    ordinary(user)
    if request.method == "PATCH":
        data = payload(request, ["is_active"], ["is_active"])
        if type(data["is_active"]) is not bool:
            raise ApiProblem("invalid_status", "is_active must be a boolean.")
        user.is_active = data["is_active"]
    else:
        user.deleted_at, user.is_active = timezone.now(), False
    user.credential_version += 1
    user.save(update_fields=["is_active", "deleted_at", "credential_version"])
    if not user.is_active:
        cancel_queued(request, user)
    record(
        request,
        "identity.status_changed",
        "api_user",
        user.identifier,
        {"is_active": user.is_active, "deleted": bool(user.deleted_at)},
        owner=user,
    )
    return (
        HttpResponse(status=204)
        if request.method == "DELETE"
        else JsonResponse(user_data(user))
    )


@api_endpoint(["PUT"], master=True, identity=True)
def assign_role(request, user_identifier):
    user = target_user(user_identifier)
    ordinary(user)
    data = payload(request, ["role_identifier"], ["role_identifier"])
    role = role_for(data["role_identifier"])
    previous = str(user.role.identifier) if user.role else None
    user.role, user.credential_version = role, user.credential_version + 1
    user.save(update_fields=["role", "credential_version"])
    if "write" not in effective_permissions(user):
        cancel_queued(request, user)
    record(
        request,
        "identity.role_changed",
        "api_user",
        user.identifier,
        {"role_identifier": {"before": previous, "after": str(role.identifier)}},
        owner=user,
    )
    return JsonResponse(user_data(user))


@api_endpoint(["POST"], master=True, identity=True)
def issue_credentials(request, user_identifier):
    user = target_user(user_identifier)
    ordinary(user)
    payload(request, [])
    secret = new_secret()
    user.client_secret_hash, user.credential_identifier = (
        make_password(secret),
        uuid.uuid4(),
    )
    user.credential_version += 1
    user.save(
        update_fields=[
            "client_secret_hash",
            "credential_identifier",
            "credential_version",
        ]
    )
    record(
        request, "identity.credentials_issued", "api_user", user.identifier, owner=user
    )
    return JsonResponse(
        {
            "identifier": str(user.credential_identifier),
            "client_id": user.username,
            "client_secret": secret,
            "message": "Returned once. Previous tokens are invalid.",
        },
        status=201,
    )


@api_endpoint(["DELETE"], master=True, identity=True)
def revoke_credentials(request, credential_identifier):
    user = (
        ApiUser.objects.select_for_update()
        .filter(credential_identifier=credential_identifier, deleted_at__isnull=True)
        .first()
    )
    if not user:
        raise ApiProblem("not_found", "Credentials not found.", 404)
    ordinary(user)
    user.client_secret_hash, user.credential_version = "", user.credential_version + 1
    user.save(update_fields=["client_secret_hash", "credential_version"])
    record(
        request, "identity.credentials_revoked", "api_user", user.identifier, owner=user
    )
    return HttpResponse(status=204)


@api_endpoint(["PUT"])
def provider_token(request, user_identifier):
    user = target_user(user_identifier)
    if user.pk != request.api_user.pk and not request.api_user.is_superuser:
        raise ApiProblem("not_found", "API user not found.", 404)
    data = payload(request, ["sympla_token"], ["sympla_token"])
    try:
        user.sympla_token_encrypted = encrypt_token(data["sympla_token"])
    except ValueError:
        raise ApiProblem(
            "invalid_provider_token", "Provide a nonempty printable Sympla token."
        ) from None
    user.provider_version += 1
    user.save(update_fields=["sympla_token_encrypted", "provider_version"])
    record(
        request,
        "identity.provider_token_updated",
        "api_user",
        user.identifier,
        owner=user,
    )
    return JsonResponse(
        {"identifier": str(user.identifier), "sympla_token_configured": True}
    )


@api_endpoint(["GET", "POST"], master=True, identity=True)
def roles(request):
    if request.method == "GET":
        return collection(request, Role.objects.order_by("id"), role_data)
    data = payload(
        request, ["name", "description", "permissions"], ["name", "permissions"]
    )
    name, description = data["name"], data.get("description", "")
    if (
        not isinstance(name, str)
        or not 1 <= len(name) <= 80
        or not name.strip()
        or not name.isprintable()
        or not isinstance(description, str)
        or len(description) > 200
    ):
        raise ApiProblem(
            "invalid_role",
            "Provide a printable role name (1-80 characters) and description (up to 200).",
        )
    codes = permission_codes(data["permissions"])
    role = Role.objects.create(name=name, description=description)
    role.permissions.set(codes)
    record(
        request,
        "role.created",
        "role",
        role.identifier,
        {"name": name, "permissions": codes},
    )
    return JsonResponse(role_data(role), status=201)


def mutable_role(value):
    role = Role.objects.select_for_update().filter(identifier=value).first()
    if not role:
        raise ApiProblem("not_found", "Role not found.", 404)
    if role.is_system:
        raise ApiProblem(
            "protected_role", "System roles are immutable. Create a custom role.", 403
        )
    return role


@api_endpoint(["GET", "PATCH", "DELETE"], master=True, identity=True)
def role_detail(request, role_identifier):
    if request.method == "GET":
        role = Role.objects.filter(identifier=role_identifier).first()
        if not role:
            raise ApiProblem("not_found", "Role not found.", 404)
        return JsonResponse(role_data(role))
    role = mutable_role(role_identifier)
    if request.method == "DELETE":
        if ApiUser.objects.filter(role=role).exists():
            raise ApiProblem(
                "role_in_use", "Reassign users before deleting this role.", 409
            )
        record(request, "role.deleted", "role", role.identifier, {"name": role.name})
        role.delete()
        return HttpResponse(status=204)
    data = payload(request, ["name", "description"])
    if not data:
        raise ApiProblem("invalid_role", "Provide at least one role field.")
    for key, value in data.items():
        if (
            not isinstance(value, str)
            or len(value) > (80 if key == "name" else 200)
            or (key == "name" and (not value.strip() or not value.isprintable()))
        ):
            raise ApiProblem("invalid_role", "Invalid role name or description.")
        setattr(role, key, value)
    role.save()
    record(request, "role.updated", "role", role.identifier, data)
    return JsonResponse(role_data(role))


@api_endpoint(["PUT"], master=True, identity=True)
def role_permissions(request, role_identifier):
    role = mutable_role(role_identifier)
    codes = permission_codes(
        payload(request, ["permissions"], ["permissions"])["permissions"]
    )
    before = sorted(role.permissions.values_list("code", flat=True))
    role.permissions.set(codes)
    users = list(ApiUser.objects.select_for_update().filter(role=role).order_by("id"))
    for user in users:
        user.credential_version += 1
        user.save(update_fields=["credential_version"])
        if "write" not in effective_permissions(user):
            cancel_queued(request, user)
    record(
        request,
        "role.permissions_changed",
        "role",
        role.identifier,
        {"permissions": {"before": before, "after": codes}},
    )
    return JsonResponse(role_data(role))


@api_endpoint(["GET"], identity=True)
def permissions(request):
    return JsonResponse(
        {
            "results": [
                {"code": code, "description": description}
                for code, description in PERMISSIONS.items()
            ]
        }
    )


def rule_data(rule):
    return {
        "identifier": str(rule.identifier),
        "user_identifier": str(rule.user.identifier),
        "permission": rule.permission_id,
    }


@api_endpoint(["GET", "POST"], master=True, identity=True)
def access_rules(request):
    if request.method == "GET":
        return collection(request, AccessRule.objects.order_by("id"), rule_data)
    data = payload(
        request, ["user_identifier", "permission"], ["user_identifier", "permission"]
    )
    user = target_user(identifier(data["user_identifier"]))
    ordinary(user)
    permission_codes([data["permission"]])
    rule = AccessRule.objects.create(user=user, permission_id=data["permission"])
    user.credential_version += 1
    user.save(update_fields=["credential_version"])
    record(
        request,
        "access_rule.created",
        "access_rule",
        rule.identifier,
        {"permission": rule.permission_id, "user_identifier": str(user.identifier)},
        owner=user,
    )
    return JsonResponse(rule_data(rule), status=201)


@api_endpoint(["DELETE"], master=True, identity=True)
def remove_rule(request, rule_identifier):
    rule = AccessRule.objects.filter(identifier=rule_identifier).first()
    if not rule:
        raise ApiProblem("not_found", "Access rule not found.", 404)
    user = target_user(rule.user.identifier)
    ordinary(user)
    record(
        request,
        "access_rule.deleted",
        "access_rule",
        rule.identifier,
        {"permission": rule.permission_id},
        owner=user,
    )
    rule.delete()
    user.credential_version += 1
    user.save(update_fields=["credential_version"])
    if "write" not in effective_permissions(user):
        cancel_queued(request, user)
    return HttpResponse(status=204)


@api_endpoint(["PUT"], master=True, identity=True)
def individual_permissions(request, user_identifier):
    user = target_user(user_identifier)
    ordinary(user)
    codes = permission_codes(
        payload(request, ["permissions"], ["permissions"])["permissions"]
    )
    previous = sorted(
        AccessRule.objects.filter(user=user).values_list("permission_id", flat=True)
    )
    AccessRule.objects.filter(user=user).delete()
    AccessRule.objects.bulk_create(
        [AccessRule(user=user, permission_id=code) for code in codes]
    )
    user.credential_version += 1
    user.save(update_fields=["credential_version"])
    if "write" not in effective_permissions(user):
        cancel_queued(request, user)
    record(
        request,
        "identity.permissions_changed",
        "api_user",
        user.identifier,
        {"permissions": {"before": previous, "after": codes}},
        owner=user,
    )
    return JsonResponse(user_data(user))
