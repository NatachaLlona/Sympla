from .rbac import PERMISSIONS


def extend(schema):
    schema["tags"] = [
        {"name": name}
        for name in [
            "Identity",
            "Authorization",
            "Authentication",
            "Schedules",
            "Synchronization",
            "Events",
            "Audit",
            "Status",
        ]
    ]
    from .openapi import obj, text, integer, ref, response, operation, paged, PAGINATION

    schemas, paths = schema["components"]["schemas"], schema["paths"]
    permission_list = {
        "type": "array",
        "items": text(enum=list(PERMISSIONS)),
        "uniqueItems": True,
    }
    uid = text(format="uuid")

    def param():
        return [{"name": "identifier", "in": "path", "required": True, "schema": uid}]

    def route(
        path,
        method,
        name,
        summary,
        tag,
        result=None,
        body=None,
        code="200",
        description="",
        parameters=None,
    ):
        params = (param() if "{identifier}" in path else []) + (parameters or [])
        item = operation(
            name,
            summary,
            tag,
            ref(result) if isinstance(result, str) else result,
            code=code,
            body=ref(body) if isinstance(body, str) else body,
            parameters=params,
            description=description,
        )
        if "{identifier}" in path:
            item["responses"]["404"] = response(
                "Record not found or not accessible", ref("Error")
            )
        if method != "get":
            item["responses"]["409"] = response(
                "Duplicate record or relationship conflict", ref("Error")
            )
        paths.setdefault(path, {})[method] = item

    fields = {
        "identifier": uid,
        "client_id": text(),
        "role_identifier": {**uid, "nullable": True},
        "role": text(nullable=True),
        "is_superuser": {"type": "boolean"},
        "is_active": {"type": "boolean"},
        "created_at": text(format="date-time"),
        "permissions": permission_list,
        "role_permissions": permission_list,
        "individual_permissions": permission_list,
        "sympla_token_configured": {"type": "boolean"},
        "credential_identifier": uid,
        "credentials_active": {"type": "boolean"},
    }
    schemas["ApiUser"] = obj(fields, fields.keys())
    schemas["ApiUserCreated"] = obj(
        {
            **fields,
            "client_secret": text(
                description="Returned only on creation; store securely."
            ),
        }
    )
    schemas["ApiUserList"] = paged("ApiUser")
    schemas["CreateApiUser"] = {
        **obj(
            {
                "client_id": text(minLength=3, maxLength=100),
                "role_identifier": uid,
                "sympla_token": text(
                    format="password", writeOnly=True, minLength=1, maxLength=4096
                ),
                "client_secret": text(
                    format="password",
                    writeOnly=True,
                    minLength=8,
                    maxLength=16,
                    description="Optional; a policy-compliant secret is generated when omitted.",
                ),
            },
            ["client_id", "role_identifier", "sympla_token"],
        ),
        "additionalProperties": False,
    }
    schemas["Role"] = obj(
        {
            "identifier": uid,
            "name": text(),
            "description": text(),
            "is_system": {"type": "boolean"},
            "permissions": permission_list,
        }
    )
    schemas["RoleList"] = paged("Role")
    schemas["RoleCreate"] = {
        **obj(
            {
                "name": text(minLength=1, maxLength=80),
                "description": text(maxLength=200),
                "permissions": permission_list,
            },
            ["name", "permissions"],
        ),
        "additionalProperties": False,
    }
    schemas["PermissionReplacement"] = {
        **obj({"permissions": permission_list}, ["permissions"]),
        "additionalProperties": False,
    }
    schemas["RoleAssignment"] = {
        **obj({"role_identifier": uid}, ["role_identifier"]),
        "additionalProperties": False,
    }
    schemas["IdentityStatus"] = {
        **obj({"is_active": {"type": "boolean"}}, ["is_active"]),
        "additionalProperties": False,
    }
    schemas["ProviderTokenInput"] = {
        **obj(
            {"sympla_token": text(format="password", writeOnly=True, minLength=1)},
            ["sympla_token"],
        ),
        "additionalProperties": False,
    }
    schemas["AccessRule"] = obj(
        {
            "identifier": uid,
            "api_user_identifier": uid,
            "permission": text(enum=list(PERMISSIONS)),
        }
    )
    schemas["AccessRuleList"] = paged("AccessRule")
    schemas["AccessRuleCreate"] = {
        **obj(
            {
                "api_user_identifier": uid,
                "permission": text(enum=list(PERMISSIONS)),
            },
            ["api_user_identifier", "permission"],
        ),
        "additionalProperties": False,
    }
    schemas["IssuedCredentials"] = obj(
        {
            "identifier": uid,
            "client_id": text(),
            "client_secret": text(),
            "message": text(),
        }
    )
    admin = "Requires the section:action permission documented below. Delegated API accounts can grant only permissions they possess. The bootstrap master and system roles remain protected."
    route(
        "/me",
        "get",
        "me",
        "Read current identity and effective permissions",
        "Identity",
        "ApiUser",
        description="Available to every active authenticated identity, including a role with no operational permissions.",
    )
    route(
        "/api-users",
        "post",
        "createApiUser",
        "Create an API account with its own Sympla token",
        "Identity",
        "ApiUserCreated",
        "CreateApiUser",
        "201",
        admin
        + " The client secret is returned once; the provider token is never returned.",
    )
    route(
        "/api-users",
        "get",
        "listApiUsers",
        "List API accounts",
        "Identity",
        "ApiUserList",
        description=admin,
        parameters=PAGINATION,
    )
    route(
        "/api-users/{identifier}",
        "get",
        "getApiUser",
        "Read an API account by its unique identifier",
        "Identity",
        "ApiUser",
        description="Requires identity:read. GET /me remains available to every authenticated API account.",
    )
    route(
        "/api/users/{identifier}",
        "get",
        "getApiUserAlias",
        "Read an API account by identifier (alias)",
        "Identity",
        "ApiUser",
        description="Alias for GET /api-users/{identifier}. Same authorization checks apply.",
    )
    route(
        "/api-users/{identifier}",
        "patch",
        "setApiUserStatus",
        "Activate or deactivate an ordinary identity",
        "Identity",
        "ApiUser",
        "IdentityStatus",
        description=admin
        + " Existing tokens are revoked and queued jobs are cancelled on deactivation.",
    )
    route(
        "/api-users/{identifier}",
        "delete",
        "deleteApiUser",
        "Soft-delete an ordinary identity",
        "Identity",
        code="204",
        description=admin + " Data and audit history are preserved.",
    )
    route(
        "/api-users/{identifier}/role",
        "put",
        "assignApiUserRole",
        "Assign a role",
        "Identity",
        "ApiUser",
        "RoleAssignment",
        description=admin + " The master role cannot be assigned through this API.",
    )
    route(
        "/api-users/{identifier}/credentials",
        "post",
        "issueApiCredentials",
        "Issue replacement client credentials",
        "Identity",
        "IssuedCredentials",
        {"type": "object", "additionalProperties": False},
        "201",
        admin
        + " Send {}. The new secret is returned once and old access tokens are invalidated.",
    )
    route(
        "/credentials/{identifier}",
        "delete",
        "revokeApiCredentials",
        "Revoke current client credentials",
        "Identity",
        code="204",
        description=admin,
    )
    route(
        "/api-users/{identifier}/sympla-token",
        "put",
        "setUserProviderToken",
        "Replace the write-only Sympla token",
        "Identity",
        obj({"identifier": uid, "sympla_token_configured": {"type": "boolean"}}),
        "ProviderTokenInput",
        description="Requires identity:edit. The master provider token can be changed only by the master. No other API account token is used as fallback.",
    )
    route(
        "/api-users/{identifier}/permissions",
        "put",
        "setIndividualPermissions",
        "Replace individual grants without changing the role",
        "Authorization",
        "ApiUser",
        "PermissionReplacement",
        description=admin
        + " Effective permissions are the union of role permissions and individual grants.",
    )
    route(
        "/permissions",
        "get",
        "listPermissions",
        "List read, write, edit and delete permissions",
        "Authorization",
        obj(
            {
                "results": {
                    "type": "array",
                    "items": obj({"code": text(), "section": text(), "action": text(), "description": text()}),
                }
            }
        ),
        description="Requires authorization:read. Each code combines an API section and one action: read, write, edit or delete.",
    )
    route(
        "/roles",
        "post",
        "createRole",
        "Create a role and assign permissions",
        "Authorization",
        "Role",
        "RoleCreate",
        "201",
        admin,
    )
    route(
        "/roles",
        "get",
        "listRoles",
        "List roles and their permissions",
        "Authorization",
        "RoleList",
        description=admin,
        parameters=PAGINATION,
    )
    route(
        "/roles/{identifier}",
        "get",
        "getRole",
        "Read a role",
        "Authorization",
        "Role",
        description=admin,
    )
    route(
        "/roles/{identifier}",
        "patch",
        "editRole",
        "Edit a custom role",
        "Authorization",
        "Role",
        {
            **obj(
                {
                    "name": text(minLength=1, maxLength=80),
                    "description": text(maxLength=200),
                }
            ),
            "additionalProperties": False,
        },
        description=admin,
    )
    route(
        "/roles/{identifier}",
        "delete",
        "deleteRole",
        "Delete an unused custom role",
        "Authorization",
        code="204",
        description=admin,
    )
    route(
        "/roles/{identifier}/permissions",
        "put",
        "setRolePermissions",
        "Replace a custom role permission set",
        "Authorization",
        "Role",
        "PermissionReplacement",
        description=admin + " Affected API accounts must obtain a new access token.",
    )
    route(
        "/access-rules",
        "post",
        "createAccessRule",
        "Add an individual permission grant",
        "Authorization",
        "AccessRule",
        "AccessRuleCreate",
        "201",
        admin,
    )
    route(
        "/access-rules",
        "get",
        "listAccessRules",
        "List individual permission grants",
        "Authorization",
        "AccessRuleList",
        description=admin,
        parameters=PAGINATION,
    )
    route(
        "/access-rules/{identifier}",
        "delete",
        "deleteAccessRule",
        "Remove an individual permission grant",
        "Authorization",
        code="204",
        description=admin,
    )
    schema["info"]["version"] = "3.0.0"
    schema["info"]["description"] += (
        " The startup identity is a protected master. Ordinary accounts have roles and optional individual grants. "
        "read authorizes GET, write authorizes create/sync POST, edit authorizes record PUT/PATCH, delete authorizes DELETE. "
        "Administration requires identity, roles or authorization permissions independently. Provider data is scoped to the authenticated owner."
    )

    for path, methods in paths.items():
        for method, item in methods.items():
            if method not in ("get", "post", "put", "patch", "delete") or not item.get("security", schema.get("security")):
                continue
            tag = item.get("tags", [""])[0]
            section = {"Identity": "identity", "Authorization": "authorization", "Schedules": "schedules", "Synchronization": "synchronization", "Events": "events", "Audit": "audit"}.get(tag)
            if path.startswith("/roles"):
                section = "roles"
            if path == "/me" or not section:
                continue
            action = {"get": "read", "post": "write", "put": "edit", "patch": "edit", "delete": "delete"}[method]
            if path.endswith("/credentials") and method == "post":
                action = "edit"
            code = f"{section}:{action}"
            item["x-required-permission"] = code
            item["description"] = f"Requires {code}. " + item.get("description", "")
