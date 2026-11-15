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
The fixture expects disposable database/user sympla_qa and password disposable-local-qa-only, with
permission to create/drop test databases. Django creates/drops test_sympla_qa. These fixture values
must never be deployment credentials.

The separate end-to-end command python qa/verify_docker_startup.py validates first-boot password
retries in English, Docker build/health/migrations/client setup, real HTTP token exchange, stored
schedules, worker job processing, restart persistence, credential rotation, revocation of old tokens,
restricted DB role permissions, and shutdown without deleting data. An empty provider token ensures
no live Sympla request: the test job ends with the expected upstream_configuration failure.

This owned QA stack uses project sympla-startup-qa, database port 25424, API port 18010 and .qa-local/.
Its sample passwords belong exclusively to disposable QA infrastructure. It never targets the user's
Simpla database/port 2424 or normal client credentials. CI runs both the suite and the launcher check.

Build contexts exclude .env files, SQLite files, .local secrets, QA state and Git metadata.
Limitations: no live provider smoke test, load test or infrastructure pentest. Remote deployment
requires an explicit HTTPS/reverse-proxy/database security setup.
