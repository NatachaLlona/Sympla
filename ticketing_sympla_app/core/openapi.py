"""OpenAPI contract for the plain Django views; examples contain no credentials."""


def ref(name):
    return {"$ref": "#/components/schemas/" + name}


def obj(properties, required=()):
    result = {"type": "object", "properties": properties}
    if required:
        result["required"] = list(required)
    return result


def text(**kwargs):
    return {"type": "string", **kwargs}


def integer(**kwargs):
    return {"type": "integer", **kwargs}


def response(description, schema=None):
    result = {"description": description}
    if schema:
        result["content"] = {"application/json": {"schema": schema}}
    return result


def query(name, schema, description):
    return {
        "name": name,
        "in": "query",
        "required": False,
        "schema": schema,
        "description": description,
    }


def path_id(name):
    return {"name": name, "in": "path", "required": True, "schema": integer(minimum=1)}


PAGINATION = [
    query("page", integer(minimum=1, maximum=100000, default=1), "Result page."),
    query("page_size", integer(minimum=1, maximum=100, default=50), "Items per page."),
]


def operation(
    name,
    summary,
    tag,
    result,
    code="200",
    parameters=None,
    body=None,
    example=None,
    description="",
):
    responses = {
        code: response("Success", result),
        "401": response(
            "Missing, invalid or expired access token, or revoked client.", ref("Error")
        ),
        "403": response(
            "The required permission or master authority is missing.", ref("Error")
        ),
        "405": response("Method not allowed.", ref("Error")),
        "500": response(
            "Internal error; uncommitted changes are rolled back.", ref("Error")
        ),
    }
    if parameters or body is not None:
        responses["400"] = response("Invalid parameters or body.", ref("Error"))
    result = {
        "operationId": name,
        "summary": summary,
        "tags": [tag],
        "description": description,
        "responses": responses,
    }
    if parameters:
        result["parameters"] = parameters
    if body is not None:
        media = {"schema": body}
        if example is not None:
            media["example"] = example
        result["requestBody"] = {
            "required": True,
            "content": {"application/json": media},
        }
        responses["413"] = response("Body exceeds 4096 bytes.", ref("Error"))
    return result


def paged(name, include_page=True):
    properties = {
        "count": integer(minimum=0),
        "results": {"type": "array", "items": ref(name)},
    }
    if include_page:
        properties.update(
            {"page": integer(minimum=1), "page_size": integer(minimum=1, maximum=100)}
        )
    return obj(properties, properties.keys())


DATETIME = text(format="date-time")
NULL_DATETIME = text(format="date-time", nullable=True)
JSON_OBJECT = {"type": "object", "additionalProperties": True}
SCHEMAS = {
    "Error": obj({"error": text(), "required": text()}, ["error"]),
    "ScheduleInput": {
        **obj(
            {
                "time": text(pattern="^(?:[01]\\d|2[0-3]):[0-5]\\d$", example="09:30"),
                "timezone": text(
                    maxLength=100,
                    example="Europe/Lisbon",
                    description="Required IANA timezone.",
                ),
                "active": {"type": "boolean", "default": True},
            },
            ["time", "timezone"],
        ),
        "additionalProperties": False,
    },
    "ScheduleState": {
        **obj({"active": {"type": "boolean"}}, ["active"]),
        "additionalProperties": False,
    },
    "Schedule": obj(
        {
            "id": integer(),
            "time": text(example="09:30"),
            "timezone": text(),
            "active": {"type": "boolean"},
            "next_run_at": NULL_DATETIME,
            "created_at": DATETIME,
            "created_by": text(),
        },
        ["id", "time", "timezone", "active", "next_run_at", "created_at", "created_by"],
    ),
    "QueuedRun": obj(
        {
            "id": text(format="uuid"),
            "status": text(enum=["queued"]),
            "status_url": text(),
            "message": text(),
        },
        ["id", "status", "status_url"],
    ),
    "SyncRun": obj(
        {
            "id": text(format="uuid"),
            "source": text(enum=["manual", "scheduled"]),
            "actor": text(),
            "schedule_id": integer(nullable=True),
            "scheduled_for": NULL_DATETIME,
            "status": text(
                enum=["queued", "running", "success", "failed", "cancelled"]
            ),
            "created_at": DATETIME,
            "started_at": NULL_DATETIME,
            "finished_at": NULL_DATETIME,
            "error_code": text(),
            "error_details": JSON_OBJECT,
            "counts": JSON_OBJECT,
        }
    ),
    "Event": obj(
        {
            "id": integer(),
            "external_id": text(),
            "version": integer(minimum=1),
            "updated_at": DATETIME,
            "data": JSON_OBJECT,
        }
    ),
    "EventVersion": obj(
        {
            "id": integer(),
            "version": integer(minimum=1),
            "created_at": DATETIME,
            "run_id": text(format="uuid"),
            "data": JSON_OBJECT,
            "differences": JSON_OBJECT,
        }
    ),
    "AuditLog": obj(
        {
            "id": integer(),
            "interaction_id": text(format="uuid"),
            "created_at": DATETIME,
            "actor": text(),
            "action": text(),
            "resource": text(),
            "target_id": text(),
            "differences": JSON_OBJECT,
            "outcome": text(),
        }
    ),
    "RequestLog": obj(
        {
            "id": integer(),
            "interaction_id": text(format="uuid"),
            "started_at": DATETIME,
            "finished_at": DATETIME,
            "actor": text(),
            "method": text(),
            "path": text(),
            "http_status": integer(minimum=100, maximum=599),
        }
    ),
}
for name in ["SyncRun", "Event", "EventVersion", "AuditLog", "RequestLog"]:
    SCHEMAS[name + "List"] = paged(name)
SCHEMAS["ScheduleList"] = paged("Schedule", include_page=False)
PATHS = {
    "/ping/": {
        "get": {
            "operationId": "ping",
            "summary": "Check process liveness",
            "tags": ["Status"],
            "security": [],
            "responses": {
                "200": {
                    "description": "pong",
                    "content": {"text/html": {"schema": text(), "example": "pong"}},
                }
            },
        }
    },
    "/api/v1/schedules/": {
        "get": operation(
            "listSchedules",
            "List daily schedules",
            "Schedules",
            ref("ScheduleList"),
            parameters=PAGINATION
            + [
                query(
                    "active",
                    {"type": "boolean"},
                    "true = active, false = inactive. Omit to list both.",
                )
            ],
        ),
        "post": operation(
            "createSchedule",
            "Create a daily schedule",
            "Schedules",
            ref("Schedule"),
            code="201",
            body=ref("ScheduleInput"),
            example={"time": "09:30", "timezone": "Europe/Lisbon", "active": True},
            description="Requires schedules:write. Confirmed means active. Maximum 100 schedules.",
        ),
    },
    "/api/v1/schedules/{schedule_id}/": {
        "patch": operation(
            "setScheduleState",
            "Activate or deactivate a schedule",
            "Schedules",
            ref("Schedule"),
            parameters=[path_id("schedule_id")],
            body=ref("ScheduleState"),
            example={"active": False},
            description="Requires schedules:edit. Deactivation cancels queued jobs, not already running jobs.",
        ),
        "delete": operation(
            "deleteSchedule",
            "Delete an active or inactive schedule",
            "Schedules",
            None,
            code="204",
            parameters=[path_id("schedule_id")],
            description="Requires schedules:delete. Soft deletion preserves audit history and cancels queued jobs.",
        ),
    },
    "/api/v1/sync/": {
        "post": operation(
            "queueManualSync",
            "Request manual Sympla synchronization",
            "Synchronization",
            ref("QueuedRun"),
            code="202",
            body={"type": "object", "additionalProperties": False},
            example={},
            description="Requires synchronization:write and a running worker. Queues a job without a schedule. A 202 response confirms queuing; monitor sync-runs for completion.",
        )
    },
    "/api/v1/sync-runs/": {
        "get": operation(
            "listSyncRuns",
            "List synchronization runs and results",
            "Synchronization",
            ref("SyncRunList"),
            parameters=PAGINATION,
        )
    },
    "/api/v1/events/": {
        "get": operation(
            "listEvents",
            "List current database events",
            "Events",
            ref("EventList"),
            parameters=PAGINATION,
        )
    },
    "/api/v1/events/{event_id}/versions/": {
        "get": operation(
            "listEventVersions",
            "List event versions and field changes",
            "Events",
            ref("EventVersionList"),
            parameters=[path_id("event_id")] + PAGINATION,
            description="event_id is the local ID returned by GET /api/v1/events/. Versions are immutable.",
        )
    },
    "/api/v1/audit-logs/": {
        "get": operation(
            "listAuditLogs",
            "List mutation audit history",
            "Audit",
            ref("AuditLogList"),
            parameters=PAGINATION
            + [
                query(name, text(), "Exact filter.")
                for name in ["resource", "target_id", "actor"]
            ],
        )
    },
    "/api/v1/request-logs/": {
        "get": operation(
            "listRequestLogs",
            "List API access history",
            "Audit",
            ref("RequestLogList"),
            parameters=PAGINATION,
            description="Does not record headers, tokens, bodies or query parameters.",
        )
    },
}
PATHS["/api/v1/schedules/"]["post"]["responses"]["409"] = response(
    "Duplicate schedule or schedule limit reached.", ref("Error")
)
PATHS["/api/v1/sync/"]["post"]["responses"]["409"] = response(
    "A manual run is already pending.", ref("Error")
)
for path in ["/api/v1/schedules/{schedule_id}/", "/api/v1/events/{event_id}/versions/"]:
    for item in PATHS[path].values():
        item["responses"]["404"] = response("Record not found.", ref("Error"))
SCHEMA = {
    "openapi": "3.0.3",
    "info": {
        "title": "Sympla Integration API",
        "version": "2.0.0",
        "description": "Use Authorize with your API client ID and client secret. Swagger calls the token endpoint using the client_credentials grant and attaches the returned Bearer access token. Client secrets are configured by start.py and stored only as password hashes. Tokens expire and are invalidated by client secret rotation or revocation. The Sympla provider token stays on the server. Try it out operations change real data.",
    },
    "servers": [{"url": "/", "description": "Current server"}],
    "security": [{"ClientCredentials": []}],
    "components": {
        "securitySchemes": {
            "ClientCredentials": {
                "type": "oauth2",
                "description": "API client ID = client_id; API password = client_secret.",
                "flows": {
                    "clientCredentials": {"tokenUrl": "/api/v1/token/", "scopes": {}}
                },
            }
        },
        "schemas": SCHEMAS,
    },
    "paths": PATHS,
}
TOKEN_INPUT = obj(
    {
        "grant_type": text(enum=["client_credentials"], default="client_credentials"),
        "client_id": text(),
        "client_secret": text(format="password", writeOnly=True),
    },
    ["grant_type", "client_id", "client_secret"],
)
PATHS["/api/v1/token/"] = {
    "post": {
        "operationId": "issueAccessToken",
        "tags": ["Authentication"],
        "summary": "Generate a Bearer access token",
        "description": "Send client credentials in a form or JSON body. OAuth HTTP Basic client authentication is also supported with grant_type in the form body. Do not send credentials in query parameters. Limit: 10 requests per minute per source IP.",
        "security": [],
        "requestBody": {
            "required": True,
            "content": {
                "application/x-www-form-urlencoded": {"schema": TOKEN_INPUT},
                "application/json": {"schema": TOKEN_INPUT},
            },
        },
        "responses": {
            "200": response(
                "Access token issued",
                obj(
                    {
                        "access_token": text(),
                        "token_type": text(enum=["Bearer"]),
                        "expires_in": integer(),
                    },
                    ["access_token", "token_type", "expires_in"],
                ),
            ),
            "400": response("Invalid request or grant type", ref("Error")),
            "401": response("Invalid client credentials", ref("Error")),
            "413": response("Body exceeds 4096 bytes", ref("Error")),
            "429": response(
                "Too many token requests; retry after 60 seconds", ref("Error")
            ),
        },
    }
}

PATHS["/api/v1/sync-runs/{run_id}/"] = {
    "get": operation(
        "getSyncRun",
        "Read a synchronization result and diagnostic details",
        "Synchronization",
        ref("SyncRun"),
        parameters=[
            {
                "name": "run_id",
                "in": "path",
                "required": True,
                "schema": text(format="uuid"),
            }
        ],
    )
}
PATHS["/api/v1/sync-runs/{run_id}/"]["get"]["responses"]["404"] = response(
    "Run not found", ref("Error")
)
PATHS["/api/v1/sync/"]["post"]["responses"]["503"] = response(
    "Sympla credentials or host are not configured", ref("Error")
)

from .identity_schema import extend

extend(SCHEMA)
from .integration_schema import extend as extend_integrations
extend_integrations(SCHEMA)
from .statistics_schema import extend as extend_statistics
extend_statistics(SCHEMA)
