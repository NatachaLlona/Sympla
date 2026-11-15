# Validation

The application is started with start.py, running PostgreSQL, API and worker in Docker.
ANALISE.md describes the imported prototype and is historical.

Tests cover schedules, read/write permissions, token issuance with JSON/form/HTTP Basic, expiration,
rotation/revocation, rate limiting, legacy-token rejection, password rules, immutable history,
transaction rollback, event versions, worker integration, pagination, DST, concurrent workers/schedulers,
Swagger/OpenAPI and JSONC configuration. OpenAPI 3.0.3 passed openapi-spec-validator.

Final result: all 35 tests passed with Python 3.13 and PostgreSQL 17. SQLite passed 33 and skipped
the two PostgreSQL-only concurrency checks. The complete Docker launcher test also passed,
including restart persistence and client-secret rotation with invalidation of old tokens.

Runtime direct dependencies are pinned. Tests use Python 3.13 and Django 5.2.19 in Docker, with a
disposable PostgreSQL 17 and mocked upstream responses. No live Sympla credentials or normal data are used.

```powershell
docker build -f qa/Dockerfile -t sympla-sync-qa-tests .
docker run --rm --env DJANGO_SECRET_KEY=isolated-test-key-at-least-fifty-characters-long-not-for-production sympla-sync-qa-tests
```

For PostgreSQL tests, add TEST_POSTGRES_HOST=host.docker.internal and TEST_POSTGRES_PORT=55439.
The fixture expects disposable database/API account sympla_qa and password disposable-local-qa-only, with
permission to create/drop test databases. Django creates/drops test_sympla_qa. These fixture values
must never be deployment credentials.

The separate end-to-end command python qa/verify_docker_startup.py validates first-boot password
retries in English, Docker build/health/migrations/client setup, real HTTP token exchange, stored
schedules, worker job processing, restart persistence, credential rotation, revocation of old tokens,
restricted DB role permissions, and shutdown without deleting data. An empty provider token ensures
no live Sympla request: the test job ends with the expected upstream_configuration failure.

This owned QA stack uses project sympla-startup-qa, database port 25424, API port 18010 and .qa-local/.
Its sample passwords belong exclusively to disposable QA infrastructure. It never targets the API account's
Simpla database/port 2424 or normal client credentials. CI runs both the suite and the launcher check.

Build contexts exclude .env files, SQLite files, .local secrets, QA state and Git metadata.
Limitations: no live provider smoke test, load test or infrastructure pentest. Remote deployment
requires an explicit HTTPS/reverse-proxy/database security setup.

Import troubleshooting regression: missing provider configuration now returns actionable 503 before
manual queuing; run responses link to a detail endpoint. Safe diagnostics retain HTTP status/page and
English failure messages without response bodies or cursors. Tests cover Sympla terminal pages that
omit next_cursor/has_next for empty, short and exactly-full batches.

Live verification after the import fix: an authorized account read returned HTTP 200 and three events.
The normal Docker worker successfully processed scheduled imports and a manual import; three events
and three initial versions were persisted. Repeated reads reported three unchanged events and did not
create duplicate versions. Earlier failures remain in the execution/audit history. Automated QA still
uses only mocks or disposable infrastructure. Regression suite: 39 tests passed on Python 3.13/PostgreSQL.

RBAC regression coverage: protected bootstrap master, UUID identity lookup/alias, role lifecycle,
independent permission enforcement, individual grants, client issue/revoke, deactivation, access-token
invalidation, encrypted/write-only provider credentials, cross-API account access denial, no global fallback,
and stale-import rollback after provider changes. The Docker launcher additionally provisions a
read-only ordinary client and verifies its provider configuration and inability to trigger imports.
Legacy upgrade checks preserve records and separate the ownership backfill from NOT NULL DDL to
avoid PostgreSQL deferred-FK trigger conflicts. All 51 tests passed on Python 3.13/PostgreSQL 17.

Live upgrade verification: a private pre-upgrade database backup was saved. The running stack preserved
3 events, 3 versions, 9 schedules and 12 historical runs and assigned their ownership to the master.
The API no longer has a global provider token configured; the master provider credential is encrypted.
The public Swagger schema exposes Identity/Authorization, the UUID lookup alias, mandatory per-API account
provider token input and the four permission codes. No QA API accounts were created in the normal instance.

Swagger native-dialog regression: all 52 tests passed in Python 3.13/PostgreSQL. Checks cover absence
of Basic challenges on invalid API credentials, omission of cached browser authentication, qualified
account identifiers and the existing role/ownership flows. A live comparison confirmed every API
client ID, credential version and chosen-secret hash remained unchanged after the naming migration.
The Docker launcher test also passed with pre-existing credentials and the unchanged authentication flow.
