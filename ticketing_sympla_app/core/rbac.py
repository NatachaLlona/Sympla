from .models import Permission, Role, AccessRule

PERMISSIONS = {
    "read": "Read own data",
    "write": "Create schedules and request synchronization",
    "edit": "Edit existing records",
    "delete": "Delete existing records",
}
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
        ("reader", ["read"]),
        ("operator", list(PERMISSIONS)),
        ("master", list(PERMISSIONS)),
    ]:
        role, created = Role.objects.get_or_create(
            name=name, defaults={"is_system": True}
        )
        if created:
            role.permissions.set(codes)


def effective_permissions(user):
    if not user.is_active or user.deleted_at:
        return set()
    if user.is_superuser:
        return set(PERMISSIONS)
    role = (
        set(user.role.permissions.values_list("code", flat=True))
        if user.role_id
        else set()
    )
    direct = set(
        AccessRule.objects.filter(user=user).values_list("permission_id", flat=True)
    )
    return role | direct


def permitted(user, permission):
    return permission in effective_permissions(user)
