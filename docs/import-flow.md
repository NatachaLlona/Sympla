# Program logic flowcharts

These Mermaid diagrams describe the implemented logic in [views.py](../ticketing_sympla_app/core/views.py),
[services.py](../ticketing_sympla_app/core/services.py),
[connectors.py](../ticketing_sympla_app/core/connectors.py) and
[integrations.py](../ticketing_sympla_app/core/integrations.py).
They render directly on GitHub. Read the [ERD](data-model.md) for tables, keys and cardinalities.

## Manual and scheduled entry points

```mermaid
flowchart TD
    M["POST /api/v1/sync/"] --> A{"Valid Bearer token and synchronization:write?"}
    A -->|No| REJECT["Return 401 or 403; retain safe request log"]
    A -->|Yes| BODY{"Valid JSON and optional integration_id?"}
    BODY -->|No| INVALID["Return 400; retain request log"]
    BODY -->|Yes| SELECT["Select the owned integration or the default"]
    SELECT --> AVAILABLE{"Integration exists and is active?"}
    AVAILABLE -->|No| UNAVAILABLE["Return 400, 404 or 409 as applicable"]
    AVAILABLE -->|Yes| CONFIG{"Connector credentials and configuration valid?"}
    CONFIG -->|No| SERVICE["Return 503 with safe configuration error"]
    CONFIG -->|Yes| PENDING{"Manual run already queued or running for this integration?"}
    PENDING -->|Yes| CONFLICT["Return 409: sync_pending"]
    PENDING -->|No| QUEUE["Create queued SyncRun and sync.queued audit record"]
    QUEUE --> ACCEPT["Return 202 with run ID and status URL"]

    T["Worker scheduler tick"] --> DUE["Find due, active, nondeleted schedules with active owners and integrations"]
    DUE --> PERMISSION{"Owner has synchronization:write?"}
    PERMISSION -->|No| SKIP["Skip this schedule"]
    PERMISSION -->|Yes| SQUEUE["Create scheduled SyncRun and sync.queued audit record"]
    SQUEUE --> NEXT["Advance next_run_at to the next daily occurrence"]
    NEXT --> COALESCE["Missed days are coalesced into one due occurrence"]
```

Queue and schedule updates use short database transactions and the Coordinator row lock. A successful
manual response confirms queuing, not that events have been imported. Duplicate scheduled occurrences
are prevented by the schedule/time uniqueness constraint. The persistent worker sleeps five seconds
between ticks after finishing its current work; external collection may therefore delay the next tick.

## Worker execution

```mermaid
flowchart TD
    TICK["Worker tick: enqueue due schedules, then process one run"] --> SLOT{"Another run for this provider already running?"}
    SLOT -->|Yes| WAIT["No run claimed; retry on a later tick"]
    SLOT -->|No| JOB{"Queued run available?"}
    JOB -->|No| WAIT
    JOB -->|Yes| AUTH{"Owner still authorized and integration active, owned and nondeleted?"}
    AUTH -->|No| CANCEL["Mark run cancelled and append audit record"]
    AUTH -->|Yes| CLAIM["Snapshot provider version, integration revision and connector version"]
    CLAIM --> RUNNING["Set running status and provider running slot; audit start"]
    RUNNING --> COLLECT["Registered connector collects events using API-account credentials"]
    COLLECT --> FETCH{"Collection successful?"}
    FETCH -->|No| FAIL["Mark run failed, release slot, append safe failure audit and server log"]
    FETCH -->|Yes| PERSIST["Execute atomic event persistence transaction"]
    PERSIST --> RESULT{"Persistence successful?"}
    RESULT -->|No| ROLLBACK["Roll back all event, relation, version and observation changes"]
    ROLLBACK --> FAIL
    RESULT -->|Yes| SUCCESS["Run is successful; counts and collection time committed; slot released"]
```

The network request runs outside the persistence transaction. Claiming uses the Coordinator lock and
a unique provider running slot, so one import per provider runs at a time. Changing provider credentials,
integration configuration or authorization during collection prevents stale data from committing.
The version values are captured when the worker claims a job, rather than when the job is queued.

## Atomic persistence and event versioning

```mermaid
flowchart TD
    BEGIN["Begin database transaction; lock Coordinator, run, owner and integration"] --> VALID{"Authorization, provider version, integration revision and connector version still match?"}
    VALID -->|No| ERROR["Raise safe import error; roll back transaction"]
    VALID -->|Yes| TIME["Record collection timestamp and initialize counts"]
    TIME --> MORE{"Another collected event?"}
    MORE -->|No| FINISH["Mark run successful; save counts and collection time; append success audit"]
    FINISH --> COMMIT["Commit all changes together"]
    MORE -->|Yes| NORMALIZE["Connector normalizes event into allowed canonical fields"]
    NORMALIZE --> UNIQUE{"Valid payload and event ID not repeated in this batch?"}
    UNIQUE -->|No| ERROR
    UNIQUE -->|Yes| HASH["Hash sanitized event and find or create by integration plus external ID"]
    HASH --> SAME{"Fingerprint unchanged?"}
    SAME -->|Yes| KEEP["Keep content version; update first and last observation references"]
    KEEP --> OBSOLD["Append observation referencing the existing EventVersion"]
    OBSOLD --> COUNTOLD["Increment unchanged count"]
    COUNTOLD --> MORE
    SAME -->|No| PROJECT["Update event columns, address, host and categories"]
    PROJECT --> VERSION["Increment version; append immutable snapshot and field differences"]
    VERSION --> OBSNEW["Append observation referencing the new EventVersion"]
    OBSNEW --> AUDIT["Append event audit with event ID, integration ID and external ID"]
    AUDIT --> COUNTNEW["Increment created or updated count"]
    COUNTNEW --> MORE
```

Any exception in normalization, projection, version creation, observation creation or auditing rolls
back the entire persistence transaction. The worker then writes the failed run status and safe failure
evidence in a separate transaction. An empty successful response completes with zero received events;
an event missing from a response is not inferred to be deleted.

An unchanged event still receives an immutable observation. Historical observations reconstructed
by migrations are marked `legacy_version` and are separate from new `import` observations.

## Integration lifecycle

```mermaid
flowchart TD
    API["Integration CRUD request"] --> GUARD{"Valid Bearer token and matching integrations action permission?"}
    GUARD -->|No| DENY["Return 401 or 403"]
    GUARD -->|Yes| ACTION{"Operation?"}
    ACTION -->|GET| READ["Read owned, nondeleted configuration"]
    ACTION -->|POST| CREATE["Validate registered provider, fields, uniqueness and limit; create owned integration"]
    ACTION -->|PATCH| EDIT["Update allowed fields; increment revision; audit change"]
    EDIT --> ACTIVE{"Integration remains active?"}
    ACTIVE -->|No| CANCEL["Cancel queued runs; running imports fail their revision check before commit"]
    ACTIVE -->|Yes| RETAIN["Existing schedules retain their integration link"]
    ACTION -->|DELETE| DELETE["Soft-delete integration, increment revision and disable its active schedules"]
    DELETE --> CANCEL
    DELETE --> HISTORY["Preserve events, versions, observations and configuration history in audit logs"]
```

GET requires `integrations:read`, POST requires `integrations:write`, PATCH requires
`integrations:edit`, and DELETE requires `integrations:delete`. Configuration mutations and their
audit records commit together. Integration management permissions do not themselves authorize an import.

## Statistical import branch

```mermaid
flowchart TD
    CLAIM[IBGE container claims only IBGE jobs] --> SCOPE[Validate configured states and municipalities]
    SCOPE --> FETCH[Download bounded official ZIP and CSV products]
    FETCH --> MAP[Map original codes to population, age and income indicators]
    MAP --> COVERAGE[Record missing neighborhoods, explicit districts and different source universes]
    COVERAGE --> STATE[Read state income directly from the official aggregate API]
    STATE --> ATOMIC[Begin statistical persistence transaction and recheck authorization and integration revision]
    ATOMIC --> GEO[Relate geography, indicator, category, period and exact decimal value]
    GEO --> VERSION[Append a content version only when value or source status changes]
    VERSION --> OBSERVE[Append observation and source checksum even when unchanged]
    OBSERVE --> COMMIT[Commit statistics, provenance, coverage and success or partial status together]
    ATOMIC -->|Any persistence error| ROLLBACK[Roll back batch and record failed run separately]
```

State income failures are coverage gaps, not inferred municipal averages. A completed run is partial
when official data is unavailable, suppressed or has different source universes. Sympla event imports
continue to use the event persistence branch above; statistical records never enter event tables.
