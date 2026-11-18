# Sympla Integration

Independent [audience map module](docs/audience-map.md): `http://127.0.0.1:8012/map/`.
The [analysis workspace](docs/analysis-workspace.md) is available at `http://127.0.0.1:8012/map/workspace.html`:
sales CSV uploads, saved scenarios, comparisons, reports, quality and local source-update alerts.
Filter owned events, age cohorts and locality income, then inspect official IBGE density bubbles
with zoom, source provenance and explicit geography coverage.

A relational business database fed by integrations, intended to support reports and sales insights
for people and AI systems. Implemented domains are Sympla events and IBGE Census 2022 population, age and income statistics, collected through
daily or on-demand integration jobs. File uploads, sales entities and report generation are future work.

## Modular integration containers

Sympla and IBGE run in separate Docker services and images: `integration-sympla` and `integration-ibge`.
The PostgreSQL relational database and authenticated API are shared. Start all services with `python start.py`.
See [IBGE configuration, supported geography levels and coverage](docs/ibge-integration.md) for the
São Paulo/SP example, official indicators, query endpoints and honest neighborhood/district distinctions.

## Relational events, integration CRUD and lineage

Project diagrams: [Entity-relationship diagram (ERD)](docs/data-model.md) and
[program logic flowcharts](docs/import-flow.md). Both documents use Mermaid and render on GitHub.

Events now have typed relational columns for their core attributes and related address, host and
primary/secondary category records. The sanitized source snapshot remains available as `data` for
compatibility and immutable change history. Date strings and coordinates retain source formatting;
no timezone or precision is inferred. They are not normalized UTC instants or numeric geographic fields.

```mermaid
erDiagram
    API_ACCOUNT ||--o{ INTEGRATION : owns
    INTEGRATION ||--o{ SCHEDULE : schedules
    INTEGRATION ||--o{ SYNC_RUN : imports
    INTEGRATION ||--o{ EVENT : identifies
    EVENT ||--o| EVENT_ADDRESS : locates
    EVENT ||--o| EVENT_HOST : presents
    EVENT ||--o{ EVENT_CATEGORY : classifies
    EVENT ||--o{ EVENT_VERSION : versions
    EVENT ||--o{ EVENT_OBSERVATION : observes
    EVENT_VERSION ||--o{ EVENT_OBSERVATION : references
    SYNC_RUN ||--o{ EVENT_OBSERVATION : collects
```

Integration management is owner-scoped and uses independent `integrations:read`, `integrations:write`,
`integrations:edit` and `integrations:delete` permissions:

- GET/POST `/api/v1/integrations/`
- GET/PATCH/DELETE `/api/v1/integrations/{integration_id}/`
- GET `/api/v1/integration-providers/`: registered connector codes and versions

Example integration creation:

```json
{"name":"Event source","provider":"sympla","active":true,"is_default":false}
```

PATCH accepts name, active and is_default. Provider and owner are immutable. DELETE soft-deletes
configuration, deactivates its schedules and cancels queued imports; existing events, versions and
lineage remain readable. Changing a configuration during collection prevents that result from committing.
Selecting a default does not rewrite existing schedules. Reactivating an integration preserves its
original schedules; schedules disabled by deletion cannot be restored by undeleting the integration.

Each API account receives a default Sympla integration. Sympla credentials remain encrypted and scoped
to the API account: multiple Sympla integrations for the same API account use that account's token,
not separate Sympla credentials. No arbitrary upstream URLs or dynamic code imports are accepted.
Future connectors implement configuration_error, collect and normalize through the explicit registry
in core/connectors.py; they reuse the same transactional persistence, versioning and lineage pipeline.
The production registry contains Sympla event and IBGE statistical connectors.

Schedule creation and POST `/api/v1/sync/` accept an optional integration_id. Omission selects the
active default integration. Existing schedules remain linked to their migrated integration. Pending
manual imports are limited per integration. Imports still require synchronization:write independently
of integration management permissions.

- GET `/api/v1/events/`: relational event fields, related records and compatible data snapshot;
  optional integration_id and city filters.
- GET `/api/v1/events/{event_id}/`: one event with first/last observation and latest run references.
- GET `/api/v1/events/{event_id}/versions/`: immutable content changes.
- GET `/api/v1/events/{event_id}/observations/`: every successful import observation, including unchanged events.

Lineage links the source integration, external event ID, synchronization run, content version,
collection time, fingerprint and transformation version. Observations are append-only in PostgreSQL,
and runtime database permissions prohibit their modification or deletion. An import commits event
relations, versions, observations and its success status together; any failure rolls them back together.
The fingerprint covers the sanitized normalized event, not an unsanitized upstream HTTP response.

Migration preserves event identifiers, historical versions, API credentials and existing schedules.
Known historical versions produce observations marked evidence_type=legacy_version and
transformation_version=legacy.snapshot.v1, using the original version-record timestamp. Those are
reconstructed evidence, not newly verified fetch times. Previous unchanged imports cannot be reconstructed;
new imports record them from this version onward. Missing events are not inferred to be deleted.

## Start

The [demographic frontend](docs/demographic-frontend.md) runs in its own container at
**http://127.0.0.1:8011/**. Search imported IBGE age cohorts by location and analysis year, inspect
calculation bounds and provenance, and export CSV. Ages are aligned by the calendar-year difference
from the source census; this does not model births, deaths or migration.

Requirements: Python 3.10+ on the host and Docker Desktop/Engine with Linux containers and Docker Compose v2.
The API and integration containers run on Python 3.13 in Docker. A host virtual environment is not required.

```powershell
python start.py
```

In this workspace, C:\Dev\ticketing_sympla\start.py forwards to the maintained release checkout.
In a Git clone, use start.py from the repository root. The launcher prints the configuration path.

First launch prompts in English for the database account name/password, API client ID/secret, and an optional
Sympla provider token. Password input is hidden and confirmation is required. Invalid passwords explain
the rules and prompt again: **8 to 16 characters, uppercase, lowercase, digit and special character**;
printable ASCII only, no spaces. Database credentials and API credentials are separate.

The launcher builds the image, starts PostgreSQL, applies migrations, creates a restricted runtime
DB role and the initial write-enabled API client, then starts the API and worker. Subsequent launches
reuse credentials and persistent data. You may close the terminal after the Ready message.

Swagger: **http://127.0.0.1:8010/docs/** (also /swagger/).

## Configuration

Edit config.jsonc before first launch. Comments and trailing commas are supported.

```jsonc
{
  "database": { "name": "Simpla", "port": 2424 },
  "api": { "port": 8010 },
  "frontend": { "port": 8011 },
  "auth": { "token_ttl_seconds": 3600 },
  "docker": { "project_name": "sympla" }
}
```

PostgreSQL is published on host port 2424; containers connect to db:5432 internally.
Both PostgreSQL and the API bind only to 127.0.0.1. Port changes apply on the next launch.
Changing the database name/project after initialization is blocked: start.py never silently renames,
replaces or deletes existing databases. Plan an explicit migration or a separate new instance instead.

Credentials live under .local/, excluded from Git and Docker builds. The launcher restricts this directory
to the current operating-system account (and SYSTEM on Windows). Individual files are mounted as Compose secrets; passwords
are not Docker command arguments or environment values. The API client secret bootstrap file is cleared
after its password hash is saved. Database and Django secret files must remain available for restarts.
Protect this directory and backups of it and the PostgreSQL volume.

If omitted during setup, run python start.py --configure-sympla for the master account.
No provider credential is included in the code. Old SQLite/prototype data is not imported automatically.

```powershell
python start.py --check
python start.py --logs
python start.py --stop
python start.py --reset-api-client
```

Stop preserves database volumes. Reset prompts for a new API client secret and invalidates existing
tokens. The launcher never deletes volumes automatically. Use --config PATH --state-dir PATH with
a distinct Docker project and ports to isolate another instance.

## Authentication and Swagger

**API client ID = client_id. API password = client_secret.** These credentials are exchanged for an
expiring opaque Bearer token through the client credentials flow. They are separate from both the
Sympla provider token and the database credentials.

In Swagger, click Authorize, enter the client ID and client secret chosen during startup, then click
Authorize again. Swagger calls POST /api/v1/token/ and attaches the returned token to API requests.
You do not need to generate/paste the token manually. Authorization is not persisted across reloads.
When the token expires, authorize again.

Direct clients may call:

```http
POST /api/v1/token/
Content-Type: application/json

{
  "grant_type": "client_credentials",
  "client_id": "your-client-id",
  "client_secret": "your-client-secret"
}
```

The response contains access_token, token_type (Bearer) and expires_in in seconds (default 3600).
Subsequent requests use Authorization: Bearer <access_token>. Form-urlencoded and HTTP Basic client
authentication are also supported for OAuth tooling. Do not put credentials in query strings.
There are no password grants, refresh tokens or arbitrary scopes. Rate limit: 10 token requests per
minute per source IP; follow Retry-After on 429. Client rotation/revocation invalidates tokens immediately.
Old non-expiring static tokens are no longer accepted. Only password hashes and token digests are stored;
API logs never record token request/response bodies or authorization headers.

The first client is write-enabled. Operators can provision additional clients with the administrative
management command api_user create CLIENT_ID (read-only) or api_user create CLIENT_ID --write, or
rotate/revoke existing clients. Those commands require the migration-owner database connection.
There is no anonymous client-registration endpoint.

OpenAPI: /openapi.json. Swagger assets are bundled locally, without an external CDN/validator.
DJANGO_DOCS_ENABLED=false disables the documentation, schema and assets.

## API

Except for the token endpoint, all /api/v1/ routes require an access token. Write operations require
the corresponding section:action permission. Lists accept page and page_size (1 to 100).

| Method | Route | Purpose |
| --- | --- | --- |
| POST | /api/v1/token/ | Exchange client credentials for a token |
| POST | /api/v1/schedules/ | Create a daily active/inactive schedule |
| GET | /api/v1/schedules/?active=true | List active schedules; omit filter for both states |
| PATCH | /api/v1/schedules/{id}/ | Activate/deactivate with {"active":true} |
| DELETE | /api/v1/schedules/{id}/ | Soft-delete either state and cancel queued occurrences |
| POST | /api/v1/sync/ | Send {} to queue a manual import; returns 202 and run ID |
| GET | /api/v1/sync-runs/ | Read status, counts and safe error codes |
| GET | /api/v1/events/ | Read current events |
| GET | /api/v1/events/{id}/versions/ | Read versions and field differences |
| GET | /api/v1/audit-logs/ | Read changes; filters: resource, target_id, actor |
| GET | /api/v1/request-logs/ | Read access history, including denied attempts |

Schedule example: {"time":"09:30","timezone":"Europe/Lisbon","active":true}.
Each recurs daily in its explicit IANA zone. Confirmed means active. Maximum 100 nondeleted schedules;
duplicate time/zone pairs return 409. Deactivation/deletion cancels queued scheduled jobs, while running
jobs finish. /ping/ is public process liveness. The unsafe legacy /update/ route is removed.

## Synchronization and recovery

The worker runs automatically in Docker, checking schedules every five seconds between imports.
Manual jobs require no schedule and may queue behind scheduled jobs; a second unfinished manual job
returns 409. A global running slot prevents concurrent imports. After downtime, one overdue occurrence
per schedule is queued; missed days are coalesced. DST gaps are skipped; ambiguous times run once.

Every upstream page is validated before an atomic database import. New events start at version 1;
identical documented data creates no version. Changes preserve snapshots and before/after field
values with JSON Pointer paths. Events absent from later responses are retained: absence does not
prove deletion or cancellation. Current events use allowlisted JSON fields and string external IDs.
The original SQL file is historical design material; Django migrations are the implemented schema.
There is no ticket sale, payment processing or attendee ingestion.

If a worker is interrupted during a run, its running slot remains held. Stop and verify all workers,
then use recover_sync RUN_UUID --workers-stopped with an administrative connection before restarting.
This avoids an old worker committing after a replacement. Failures remain visible in sync-runs.

## Security and deployment

The supplied stack is a local loopback deployment: DEBUG=false, with HTTP explicitly enabled for local
testing and PostgreSQL TLS disabled on its private Docker connection. Remote production requires HTTPS,
trusted forwarding, appropriate database TLS, edge rate limits, backups, retention and monitoring.
Do not expose the local stack as-is.

API/worker run as non-root containers with a read-only filesystem and no extra capabilities. The runtime
DB role is not a superuser and cannot update/delete audit/version history or truncate tables. History
also has append-only triggers; DB owners can still change protections. Business changes and audit
evidence commit together, with historical actor names preserved.

Sympla requests only target HTTPS api.sympla.com.br; redirects/environment proxies are disabled.
Pagination, bytes, event count and elapsed-time checks are bounded. Connection/read timeouts are used,
not a hard process deadline. Safe error codes replace upstream bodies and tracebacks. Restrict access
to event text and sanitize HTML before rendering it in another UI.

See VALIDATION.md. A real authorized Sympla staging import remains required before production.
## Troubleshooting imports and logs

A 202 response with status queued means only that a job was accepted, not that events were imported.
The manual response includes status_url. Follow GET /api/v1/sync-runs/{run_id}/ until status becomes
success or failed. GET /api/v1/sync-runs/ lists all scheduled and manual runs. Failures include
error_code and error_details with an English message and, for upstream HTTP errors, the status/page.
Upstream bodies, authorization headers and pagination cursors are never included in these diagnostics.

If the account provider token is missing, manual sync returns 503 before queuing.
The master may use python start.py --configure-sympla; ordinary API accounts use their own identity provider-token endpoint.
Reconfigure only after active imports finish. The Sympla token is separate from your API client secret.

From the workspace root:

```powershell
python start.py --logs
```

Direct Docker commands are also available:

```powershell
docker logs --tail 100 -f sympla-worker-1
docker logs --tail 100 -f sympla-api-1
```

GET /api/v1/audit-logs/ contains persisted business changes and failures. GET /api/v1/request-logs/
contains HTTP access records. These tables remain in PostgreSQL when containers restart; Docker's
stdout logs belong to the container and may be replaced when containers are recreated.
Sympla cursor pagination permits terminal pages containing only quantity and page_size: no next_cursor
means there is no next page. The importer supports that response even for a single-page/empty result.

## Identity, roles and API account-owned Sympla accounts

The terminal identity is the single protected master. It cannot be demoted, disabled, deleted or have
its credentials revoked through HTTP. Use start.py --reset-api-client for master credential changes.
Ordinary roles never grant protected master status. Administration can be delegated with scoped permissions.

In Swagger, first create a custom role under Authorization:

```json
{"name":"Schedule editor","permissions":["schedules:read","schedules:edit"]}
```

Then POST /api-users under Identity:

```json
{
  "client_id":"another-person",
  "role_identifier":"UUID returned when the role was created",
  "sympla_token":"that person's own Sympla provider token"
}
```

The new client secret is generated and returned once; an optional client_secret may instead be provided
if it meets the password policy. The new person uses their client ID and secret with Swagger Authorize.
Provider tokens and credential hashes are never returned by identity reads or written to audits.
Every new ordinary identity must supply its own Sympla token; there is no master/global fallback.
The bootstrap master may initially omit its provider token and configure it later.

Permissions combine an API section and an action, for example `identity:write` or `schedules:edit`.
`read` permits GET, `write` permits creation POST, `edit` permits PUT/PATCH, and `delete` permits DELETE.
Credential replacement POST uses `identity:edit`. Permissions are independent and additive across the
role and individual grants. A role with `identity:write` can create API accounts; it cannot edit or
delete them without the corresponding grants. The same applies to custom roles and schedules.

| Section | API resources |
| --- | --- |
| identity | API account records, role assignment, credentials and provider token |
| roles | Custom role creation, metadata and role permission replacement |
| authorization | Permission catalogue and individual access grants |
| integrations | Owned integration configurations and registered connector catalogue |
| demographics | Imported IBGE geography, population, age, income and statistical lineage reads |
| schedules | Daily schedules |
| synchronization | Manual imports and synchronization runs |
| events | Imported events and immutable versions |
| audit | Audit and HTTP request logs |

GET /permissions returns each code with its section, action and description. The catalogue contains
four actions per section; actions without a matching endpoint do not grant additional behavior.
Swagger documents the exact required code for every protected operation. A denied call returns 403
and required_permission. Authentication and GET /me require no resource grant: valid active API
credentials can always obtain their own Bearer token. GET /api-users/{identifier} requires identity:read.

Delegated administrators can create roles, assign roles and grant permissions only within their own
effective permissions. Replacing an existing role's permissions also requires authority over its
current permissions. Reissuing credentials cannot impersonate a more privileged API account.
The master remains protected, and system roles remain immutable.

Scheduled and manual imports require synchronization:write, including the worker's final authorization
check. Creating a schedule requires schedules:write; grant both to an API account expected to import
on its schedules. synchronization:read permits inspecting job results independently.

The migration expands old global permissions into equivalent operational permissions only. It grants
no identity, role or authorization administration to existing ordinary API accounts. Credential IDs,
client secrets, imported records and immutable history are preserved.

Identity routes use immutable UUID identifiers:

- GET /me
- POST/GET /api-users
- GET/PATCH/DELETE /api-users/{identifier}; DELETE is a soft deletion
- GET /api/users/{identifier}, the individual lookup alias
- PUT /api-users/{identifier}/role
- POST /api-users/{identifier}/credentials with {} to return a replacement secret once
- DELETE /credentials/{identifier}
- PUT /api-users/{identifier}/sympla-token with {"sympla_token":"replacement"}

Authorization routes:

- GET /permissions: scoped section:action catalogue (authorization:read)
- POST/GET /roles; GET/PATCH/DELETE /roles/{identifier}
- PUT /roles/{identifier}/permissions with {"permissions":[...]}
- PUT /api-users/{identifier}/permissions: replace individual grants without changing the role
- POST/GET /access-rules; DELETE /access-rules/{identifier}

The reader/operator/master system roles are immutable; custom roles are editable. Referenced roles
cannot be deleted. identity:read permits inspecting public API account metadata. The master can inspect all audit/access logs; ordinary API accounts with audit:read see only their own logs. Provider-derived data and schedules are owner-scoped,
including the master's normal operational routes. The same external event ID/time can exist for two
API accounts without sharing data or conflicting.

Role assignments, grant changes, account status changes and credential changes invalidate affected
access tokens. Reauthorize after an approved role/grant change. Losing synchronization:write permission or deactivation
cancels queued imports. Authority and the provider version are checked again before a running import
commits; changes during an upstream fetch prevent a stale result from being saved.

Provider tokens are encrypted in PostgreSQL using Fernet authenticated encryption. The key lives
separately in .local/provider_encryption_key, mounted as a Docker secret. Back up that key with the DB;
a replacement key cannot decrypt existing values. Startup refuses to regenerate a missing initialized
key. identity:edit permits updating ordinary API account provider tokens. Only the master can update its own provider token. Normal restarts preserve API-updated credentials.
The raw master setup secret is available only to the bootstrap container, not API/worker containers.

The ownership migration assigns previously global events, schedules and runs to the original master.
Historical immutable audit records remain unchanged and unscoped legacy evidence is master-only.
Other legacy accounts retain reader/operator operational rights but must configure their own provider
credentials. Startup automatically supplies INITIAL_CLIENT_ID for the migration, stops API/worker
before structural changes and restarts them afterward. The worker drains its current import on shutdown.

The master provider setup file is cleared after its encrypted value is saved. Retain the encryption key and database backups.

## Swagger authentication behavior

Swagger Authorize is the single API credential entry point. A failed token exchange returns a safe
API error and a Bearer challenge, never a Basic challenge that opens the browser-native sign-in dialog.
Swagger omits cached browser authentication credentials; the explicit API Bearer header still authorizes
protected calls. The existing API client ID and selected API secret are preserved through upgrades.
Application identifiers distinguish API accounts, database accounts and operating-system accounts.
Historical SQL column names are mapped explicitly rather than changing credential data or applied history.
