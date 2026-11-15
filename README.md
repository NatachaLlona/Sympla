# Sympla Integration

Daily and on-demand event synchronization with PostgreSQL persistence, change-only event versions,
immutable history and API client authentication.

## Start

Requirements: Python 3.10+ on the host and Docker Desktop/Engine with Linux containers and Docker Compose v2.
The API and worker run on Python 3.13 in Docker. A host virtual environment is not required.

```powershell
python start.py
```

In this workspace, C:\Dev\ticketing_sympla\start.py forwards to the maintained release checkout.
In a Git clone, use start.py from the repository root. The launcher prints the configuration path.

First launch prompts in English for the database username/password, API client ID/secret, and an optional
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
  "auth": { "token_ttl_seconds": 3600 },
  "docker": { "project_name": "sympla" }
}
```

PostgreSQL is published on host port 2424; containers connect to db:5432 internally.
Both PostgreSQL and the API bind only to 127.0.0.1. Port changes apply on the next launch.
Changing the database name/project after initialization is blocked: start.py never silently renames,
replaces or deletes existing databases. Plan an explicit migration or a separate new instance instead.

Credentials live under .local/, excluded from Git and Docker builds. The launcher restricts this directory
to the current user (and SYSTEM on Windows). Individual files are mounted as Compose secrets; passwords
are not Docker command arguments or environment values. The API client secret bootstrap file is cleared
after its password hash is saved. Database and Django secret files must remain available for restarts.
Protect this directory and backups of it and the PostgreSQL volume.

If omitted during setup, put the Sympla provider token in .local/sympla_api_key and restart the stack.
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

**API username = client_id. API password = client_secret.** These credentials are exchanged for an
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
write permission. Lists accept page and page_size (1 to 100).

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

If the provider token is missing, manual sync returns 503 with a setup instruction before queuing.
Run python start.py --configure-sympla to enter the token securely and reload the API/worker.
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
