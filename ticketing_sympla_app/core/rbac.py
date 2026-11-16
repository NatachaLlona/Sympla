from .models import Permission, Role, AccessRule

SECTIONS = ("identity", "roles", "authorization", "integrations", "schedules", "synchronization", "events", "audit")
ACTIONS = ("read", "write", "edit", "delete")
PERMISSIONS = {
    f"{section}:{action}": f"{action.title()} {section} records"
    for section in SECTIONS for action in ACTIONS
}
OPERATIONAL_PERMISSIONS = {
    "read": [f"{section}:read" for section in ("integrations", "schedules", "synchronization", "events", "audit")],
    "write": ["schedules:write", "synchronization:write"],
    "edit": ["schedules:edit"],
    "delete": ["schedules:delete"],
}
OPERATOR_PERMISSIONS = [code for codes in OPERATIONAL_PERMISSIONS.values() for code in codes]
METHOD_PERMISSION = {
    "GET": "read",
    "POST": "write",
    "PUT": "edit",
    "PATCH": "edit",
    "DELETE": "delete",
}


def ensure_catalog():
    for code, description in PERMISSIONS.items():
        Permission.objects.get_or_create(
            code=code, defaults={"description": description}
        )
    for name, codes in [
        ("reader", OPERATIONAL_PERMISSIONS["read"]),
        ("operator", OPERATOR_PERMISSIONS),
        ("master", list(PERMISSIONS)),
    ]:
        role, created = Role.objects.get_or_create(
            name=name, defaults={"is_system": True}
        )
        if created:
            role.permissions.set(codes)


def effective_permissions(api_account):
    if not api_account.is_active or api_account.deleted_at:
        return set()
    if api_account.is_superuser:
        return set(PERMISSIONS)
    role = (
        set(api_account.role.permissions.values_list("code", flat=True))
        if api_account.role_id
        else set()
    )
    direct = set(
        AccessRule.objects.filter(api_account=api_account).values_list(
            "permission_id", flat=True
        )
    )
    return role | direct


def permitted(api_account, permission):
    return permission in effective_permissions(api_account)
