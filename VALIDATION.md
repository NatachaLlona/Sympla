# Validation

The original review in ANALISE.md describes the imported prototype, not the current implementation.

Implemented: recurring daily schedules with explicit IANA timezone; active/inactive state and soft deletion;
manual sync queue; persistent jobs; atomic current-event updates, snapshots and field differences;
append-only audit and API request history; operator-provisioned/revocable bearer API users.

Final validation passed with Python 3.13 in an isolated Docker image and Django 5.2.19:
23 tests passed on PostgreSQL 17; SQLite passed 21 tests and skipped two PostgreSQL-only concurrency tests.
Initial local checks also used Python 3.15.0; the final supported-version runs supersede that limitation.
PostgreSQL tests use a disposable PostgreSQL 17 container and mocked Sympla responses.
No real API credentials or production records are used in tests.

Run SQLite tests:

```powershell
$env:DJANGO_SECRET_KEY='isolated-test-key-at-least-fifty-characters-long-not-for-production'
python ticketing_sympla_app/manage.py test core --settings=ticketing_sympla_app.test_settings
```

For PostgreSQL tests, provision a disposable local database named sympla_qa with user sympla_qa,
password disposable-local-qa-only, port 55439. The test account needs permission to create/drop test databases.
Set TEST_POSTGRES_HOST=127.0.0.1 and optionally TEST_POSTGRES_PORT. Django creates/drops test_sympla_qa.
These fixed credentials are exclusively for a disposable isolated QA database and are not deployment credentials.

Coverage includes: authorization, revocation, readonly access, schedule validation and deletion,
manual queuing, absence of the unsafe legacy route, request log secret omission, transactional audit rollback,
unchanged/changed events, nested differences, partial import rollback, failure preservation,
scheduler idempotency and downtime coalescing, DST gap/fold behavior, append-only DB protection,
cursor/page pagination, redirect rejection, duplicate detection, host restrictions and concurrent worker claims.
Coverage also includes concurrent scheduler ticks, API-to-worker-to-version integration, token rotation,
oversized input rejection, and manual queuing independent of scheduled work.

Reproduce the Python 3.13 image (qa/Dockerfile is for tests, not a production web server):

```powershell
docker build -f qa/Dockerfile -t sympla-sync-qa-tests .
docker run --rm --env DJANGO_SECRET_KEY=isolated-test-key-at-least-fifty-characters-long-not-for-production sympla-sync-qa-tests
```

Add `--env TEST_POSTGRES_HOST=host.docker.internal` for the disposable database above.
Docker excludes secrets, SQLite databases, virtual environments and Git metadata from the build context.

Production deploy checks leave only HSTS subdomain/preload recommendations: these are intentionally
not enabled until the deployment domain policy is known. Do not enable them blindly.

Limitations: no live Sympla smoke test, load test, infrastructure penetration test or actual deployment.
The worker must be supervised; interrupted running jobs require explicit recovery after workers stop.
