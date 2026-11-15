# Sympla: scheduled synchronization and event history

Django service that reads the authenticated Sympla account, persists current events,
creates a new version only when documented event data changes, and records audit evidence.

## API

Interactive Swagger: `/docs/` (also `/swagger/`). OpenAPI JSON: `/openapi.json`.
Click **Authorize** and paste only the API user's token: Swagger adds `Bearer` automatically.
The UI uses same-origin bundled assets, disables external validation and does not persist tokens
across page reloads. Documentation is public; protected routes still require authentication.
Set `DJANGO_DOCS_ENABLED=false` to disable the UI, schema and assets.

Local development instance: http://127.0.0.1:8010/docs/ . To obtain a token,
from the repository root run:

```powershell
.\.venv\Scripts\python.exe ticketing_sympla_app/manage.py api_user create integration --write
```

If the username already exists, use `api_user rotate integration`. There is no default password,
password-login route or JWT: the operator provisions a high-entropy opaque API-user token.
The Sympla provider token is a separate server-side credential. A worker must be running for sync jobs.

All `/api/v1/` routes require `Authorization: Bearer <API_USER_TOKEN>`.
API user tokens are separate from the Sympla token. Read-only users cannot change schedules or trigger sync.

| Method | Route | Purpose |
| --- | --- | --- |
| POST | `/api/v1/schedules/` | Create a daily schedule, active or inactive |
| GET | `/api/v1/schedules/?active=true` | List active schedules; omit filter for both states |
| PATCH | `/api/v1/schedules/{id}/` | Activate/deactivate with `{"active":true}` |
| DELETE | `/api/v1/schedules/{id}/` | Delete either state; cancel pending scheduled jobs |
| POST | `/api/v1/sync/` | Queue manual synchronization with `{}`; returns 202 and run ID |
| GET | `/api/v1/sync-runs/` | See queued/running/success/failed/cancelled jobs and safe error codes |
| GET | `/api/v1/events/` | Read current events |
| GET | `/api/v1/events/{id}/versions/` | Read immutable versions and field differences |
| GET | `/api/v1/audit-logs/` | Read mutation history; filters: resource, target_id, actor |
| GET | `/api/v1/request-logs/` | Read API access history, including denied requests |

List routes support `page` (default 1) and `page_size` (1–100, default 50).
`/ping/` is public and reports process liveness only. The unsafe legacy `/update/` route is removed.
`/admin/` is Django's separate administration, not API authentication; business tables are not editable there.

Example schedule body (JSON):

```json
{"time":"09:30","timezone":"Europe/Lisbon","active":true}
```

Create one entry per daily time. Confirmed means active. Timezone is required: no implicit local zone.
There is a maximum of 100 nondeleted schedules. Duplicate time/zone pairs return 409.
Deleting is a soft deletion: the schedule disappears from listings but audit evidence remains.
Deleting/deactivating does not interrupt a job already running.

## Install locally

Use a fresh virtual environment and install `requirements.txt`. Django 5.2 LTS targets Python 3.13;
Python 3.13 and PostgreSQL passed the final tests. Never reuse the original copied virtual environment.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item ticketing_sympla_app/.env.example ticketing_sympla_app/.env
```

Set a new random `DJANGO_SECRET_KEY`, the server-side `SYMPLA_API_KEY`, and the correct Sympla base URL.
The default URL follows the official current contract. No credential is supplied with this repository.
For HTTP development on loopback only, set `DJANGO_DEBUG=true`. Production defaults require HTTPS.

From `ticketing_sympla_app`, with the virtual environment activated:

```powershell
python manage.py migrate
python manage.py api_user create integration --write
python manage.py runserver 127.0.0.1:8000
```

The API-user command prints a new cryptographically random token once. Save it securely; only its SHA-256
digest is stored. Do not redirect command output to application logs or paste tokens into Git.
Omit `--write` for a read-only user. Rotate/revoke locally:

```powershell
python manage.py api_user rotate integration
python manage.py api_user revoke integration
```

Rotation preserves permissions and invalidates the previous token immediately. Revocation blocks the user.
API users are provisioned by an operator, with no anonymous user-creation endpoint.

## Worker: required for both scheduled and manual runs

Run a second process and supervise it as a Windows service, systemd unit or container:

```powershell
python manage.py sync_worker
```

The worker checks schedules every five seconds and processes queued jobs. For an external scheduler,
run `python manage.py sync_worker --once` every minute; do not rely on HTTP traffic to drive scheduling.
A long synchronization delays processing until its completion. No worker means no synchronization.

Schedules persist in the database. After downtime, one overdue occurrence per schedule is queued;
missed days are coalesced rather than replayed. DST gaps are skipped; ambiguous times run at the first fold.
The queue survives restarts. Database coordination and a unique running slot allow only one sync at a time.
Manual requests work without schedules and may queue behind scheduled work. A second unfinished manual
request returns 409 to prevent accidental repeated imports.

If a worker dies during a run, the running slot intentionally remains held. Stop and verify all workers,
then mark that abandoned run failed and restart the worker:

```powershell
python manage.py recover_sync RUN_UUID --workers-stopped
```

This deliberately avoids automatic lock expiry allowing an old worker to commit after a replacement.
Failed runs are retained; retry with a new manual job after fixing the upstream/configuration problem.

## Database and history

SQLite is for single-process development. Use PostgreSQL for production and multiworker coordination.
Set `DB_ENGINE=postgresql`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DB_SSLMODE`.
Production defaults to `verify-full`; configure a trusted database CA. Use separate migration-owner and
least-privilege runtime accounts; runtime must not have schema ownership, TRUNCATE or trigger privileges.
Run Django migrations. Do not run the original `sympla_eventos_script.sql`: it is a historical design,
not the implemented schema. Existing SQLite records are not imported automatically.

Current event data and snapshots are JSON objects containing allowlisted documented Sympla fields.
Opaque external IDs are preserved as strings; event versions use a local monotonically increasing number.
The first observation creates version 1; identical content creates no new version. Nested differences use
JSON Pointer paths and before/after values with existence flags. All event mutations and their audit
records commit atomically after every upstream page is fetched and validated.

An event absent from a later API response is retained: absence may mean filtering or access changes,
not cancellation/deletion. Published/private/cancelled field changes returned by Sympla are versioned.
There is no ticket sales, payment processing, attendee ingestion or public event catalogue.

## Security and operations

- DEBUG is off by default; HTTPS redirect, secure cookies and HSTS are enabled. Configure allowed hosts.
- Bearer-only authentication: Django cookies/sessions never authorize API access.
- Every API response has X-Interaction-ID and Cache-Control: no-store. Request logs omit bodies,
  queries, headers and credentials; business logs carry explicit safe metadata and event changes.
- Audit logs, request logs and event versions have database triggers rejecting UPDATE and DELETE.
  This does not protect against the database owner or TRUNCATE; enforce runtime DB privileges.
- Sympla requests only target HTTPS api.sympla.com.br. Redirects and environment proxies are disabled.
  Pagination supports has_next and next_cursor, with duplicate detection and page/event/byte limits.
- Network calls have connection/read timeouts and an elapsed-time budget checked between chunks/pages.
  This is not a hard process deadline. Jobs fail without partially changing event data.
- Upstream bodies/exceptions are not returned to clients or saved as error text.
- Protect the reverse proxy with request limits, rate limiting, HTTPS and restricted backend access.
  Set DJANGO_TRUST_PROXY=true only when the proxy strips incoming forwarding headers
  and external clients cannot reach the backend directly.
- Event descriptions may contain personal data or HTML. Restrict API access, back up history securely,
  define retention, and sanitize HTML before rendering it in a future UI.
- No live Sympla account was queried during development; run an authorized staging smoke test before production.

See [VALIDATION.md](VALIDATION.md) for checks and [ANALISE.md](ANALISE.md) for the original prototype review.
Official contract: https://developers.sympla.com.br/api-docs .
