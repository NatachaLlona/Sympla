# Entity-relationship diagram (ERD)

This document describes the implemented database schema. Diagrams use Mermaid and render directly
on GitHub. Field lists highlight keys and business attributes; the complete field definitions are in
[models.py](../ticketing_sympla_app/core/models.py). `PK` means primary key, `FK` means foreign key,
and `UK` means unique key. Crow's-foot ends indicate many records; a circle indicates an optional record.

## Events, integrations and lineage

```mermaid
erDiagram
    API_ACCOUNT ||--o{ INTEGRATION : owns
    API_ACCOUNT ||--o{ SCHEDULE : owns
    API_ACCOUNT ||--o{ SYNC_RUN : owns
    API_ACCOUNT ||--o{ EVENT : owns
    INTEGRATION ||--o{ SCHEDULE : configures
    INTEGRATION ||--o{ SYNC_RUN : supplies
    INTEGRATION ||--o{ EVENT : identifies
    SCHEDULE o|--o{ SYNC_RUN : triggers
    SYNC_RUN o|--o{ EVENT : last_observed
    EVENT ||--o| EVENT_ADDRESS : has
    EVENT ||--o| EVENT_HOST : has
    EVENT ||--o{ EVENT_CATEGORY : classifies
    EVENT ||--o{ EVENT_VERSION : versions
    EVENT ||--o{ EVENT_OBSERVATION : tracks
    SYNC_RUN ||--o{ EVENT_VERSION : creates
    SYNC_RUN ||--o{ EVENT_OBSERVATION : collects
    EVENT_VERSION ||--o{ EVENT_OBSERVATION : references

    API_ACCOUNT {
        bigint id PK
        uuid identifier UK
        string client_id UK
    }
    INTEGRATION {
        uuid id PK
        bigint owner_id FK
        string name
        string provider
        boolean active
        boolean is_default
        integer revision
        datetime deleted_at
    }
    SCHEDULE {
        bigint id PK
        bigint owner_id FK
        uuid integration_id FK
        time time
        string timezone
        boolean active
        datetime next_run_at
        datetime deleted_at
    }
    SYNC_RUN {
        uuid id PK
        bigint owner_id FK
        uuid integration_id FK
        bigint schedule_id FK "Nullable for manual imports"
        string source
        string actor
        string status
        integer integration_revision
        integer provider_version
        string connector_version
        datetime collected_at
        datetime scheduled_for
        integer running_slot UK "Nullable except while running; provider slot"
        json counts
        string error_code
    }
    EVENT {
        bigint id PK
        bigint owner_id FK
        uuid integration_id FK
        string external_id
        string name
        string reference_id
        text detail
        string start_date "Original source date text"
        string end_date "Original source date text"
        boolean published "Nullable"
        boolean cancelled "Nullable"
        boolean private_event "Nullable"
        string url
        string image
        integer version
        string fingerprint
        json data "Sanitized source snapshot"
        datetime first_seen_at
        datetime last_seen_at
        uuid last_run_id FK "Nullable"
        datetime updated_at
    }
    EVENT_ADDRESS {
        bigint id PK
        bigint event_id FK,UK
        string name
        string address
        string address_alt
        string address_num
        string neighborhood
        string city
        string state
        string zip_code
        string country
        string lat "Original source text"
        string lon "Original source text"
    }
    EVENT_HOST {
        bigint id PK
        bigint event_id FK,UK
        string name
        text description
    }
    EVENT_CATEGORY {
        bigint id PK
        bigint event_id FK
        string kind "primary or secondary in the import pipeline"
        string name
    }
    EVENT_VERSION {
        bigint id PK
        bigint event_id FK
        uuid run_id FK
        integer version
        json data
        json differences
        datetime created_at
    }
    EVENT_OBSERVATION {
        bigint id PK
        bigint event_id FK
        bigint event_version_id FK
        uuid run_id FK
        datetime collected_at
        string fingerprint
        string transformation_version
        string evidence_type "import or legacy_version"
    }
```

Every event is identified within its integration: `(integration_id, external_id)` is unique.
Different integrations can hold the same external event ID. Events, schedules and runs also retain
their API account owner; the application validates matching ownership before collecting and committing.

| Record | Additional uniqueness rule |
| --- | --- |
| Integration | Live name per owner; at most one live default per owner |
| Schedule | Live `(owner_id, integration_id, time, timezone)` |
| SyncRun | `(schedule_id, scheduled_for)`; one running slot per provider |
| EventCategory | `(event_id, kind)` |
| EventVersion | `(event_id, version)` |
| EventObservation | `(event_id, run_id)` |

An observation records that an import saw an event, even when the content did not change. It references
the existing content version in that case. A new content version is created only when the fingerprint changes.
Versions and observations are append-only. Legacy observations reconstructed from old versions use
`evidence_type=legacy_version`; their timestamps are original version-record times, not verified fetch times.

Deleting an integration is a soft deletion: events and history remain readable. Address, host and category
rows are the current relational projection; prior values remain in immutable version snapshots.
Source date strings and coordinates retain source formatting; they are not normalized UTC instants or numeric coordinates.

## API identity and authorization

```mermaid
erDiagram
    ROLE o|--o{ API_ACCOUNT : assigned_to
    ROLE ||--o{ ROLE_PERMISSION : grants
    PERMISSION ||--o{ ROLE_PERMISSION : included_in
    API_ACCOUNT ||--o{ ACCESS_RULE : receives
    PERMISSION ||--o{ ACCESS_RULE : grants
    API_ACCOUNT ||--o{ ACCESS_TOKEN : authenticates

    ROLE {
        bigint id PK
        uuid identifier UK
        string name UK
        string description
        boolean is_system
    }
    PERMISSION {
        string code PK "section:action"
        string description
    }
    ROLE_PERMISSION {
        bigint id PK
        bigint role_id FK
        string permission_id FK
    }
    API_ACCOUNT {
        bigint id PK
        uuid identifier UK
        bigint role_id FK "Nullable"
        string client_id UK
        uuid credential_identifier UK
        string client_secret_hash
        integer credential_version
        boolean is_superuser
        boolean is_active
        text sympla_token_encrypted
        integer provider_version
        datetime deleted_at
    }
    ACCESS_RULE {
        bigint id PK
        uuid identifier UK
        bigint api_account_id FK
        string permission_id FK
    }
    ACCESS_TOKEN {
        bigint id PK
        bigint api_account_id FK
        string token_hash UK
        integer credential_version
        datetime expires_at
    }
```

`ROLE_PERMISSION` is Django's generated many-to-many join table, unique by role and permission.
`ACCESS_RULE` is unique by API account and permission. Effective permissions are the union of role and
individual grants; the protected master receives the entire permission catalogue. Token generation
requires valid API client credentials independently of resource permissions.

`API_ACCOUNT` is the qualified diagram label for the existing `ApiUser` model and `core_apiuser` table.
For compatibility, `client_id` maps to the historical `username` SQL column, and AccessRule/AccessToken
`api_account_id` maps to the historical `user_id` SQL column. Those physical names do not define separate entities.
The Sympla token belongs to the API account and is shared by that API account's Sympla integrations.

## Audit and coordination records

```mermaid
erDiagram
    AUDIT_LOG {
        bigint id PK
        uuid owner_identifier "Nullable logical owner reference"
        uuid interaction_id
        datetime created_at
        string actor
        string action
        string resource
        string target_id
        json differences
        string outcome
    }
    API_REQUEST_LOG {
        bigint id PK
        uuid owner_identifier "Nullable logical owner reference"
        uuid interaction_id UK
        datetime started_at
        datetime finished_at
        string actor
        string method
        string path
        integer http_status
    }
    COORDINATOR {
        bigint id PK "Singleton row used as a transaction mutex"
    }
    TOKEN_THROTTLE {
        bigint id PK
        string key UK "Hashed request-origin key"
        datetime window_started
        integer attempts
    }
```

These four tables have no declared foreign keys. Audit ownership, target IDs and interaction IDs are
logical references; they must not be drawn as database-enforced relationships. Audit and HTTP request
logs are append-only. Framework-managed Django tables are outside the scope of these application diagrams.

See [the program flowcharts](import-flow.md) for the runtime decisions that populate these records.

## IBGE relational statistics

```mermaid
erDiagram
    GEOGRAPHY o|--o{ GEOGRAPHY : parent_of
    INTEGRATION ||--o{ STATISTIC : owns
    GEOGRAPHY ||--o{ STATISTIC : locates
    STATISTICAL_INDICATOR ||--o{ STATISTICAL_CATEGORY : defines
    STATISTICAL_CATEGORY ||--o{ STATISTIC : classifies
    SYNC_RUN ||--o{ STATISTIC : last_observed
    STATISTIC ||--o{ STATISTIC_VERSION : versions
    SYNC_RUN ||--o{ STATISTIC_VERSION : creates
    SYNC_RUN ||--o{ IMPORT_SOURCE : downloads
    SYNC_RUN ||--o{ DATA_COVERAGE : records
    STATISTIC ||--o{ STATISTIC_OBSERVATION : tracks
    STATISTIC_VERSION ||--o{ STATISTIC_OBSERVATION : references
    IMPORT_SOURCE ||--o{ STATISTIC_OBSERVATION : supplies
    SYNC_RUN ||--o{ STATISTIC_OBSERVATION : collects

    GEOGRAPHY {
        bigint id PK
        string code
        string level "state, city, neighborhood or district"
        string name
        integer reference_year
        bigint parent_id FK "Nullable for a state"
    }
    STATISTICAL_INDICATOR {
        string code PK
        string name
        string unit
        string universe
    }
    STATISTICAL_CATEGORY {
        bigint id PK
        string indicator_id FK
        string code
        string name
        integer age_min "Nullable"
        integer age_max "Nullable"
    }
    STATISTIC {
        bigint id PK
        uuid integration_id FK
        bigint geography_id FK
        bigint category_id FK
        string period
        decimal value "Nullable for missing or suppressed values"
        string source_status
        integer version
        string fingerprint
        datetime first_seen_at
        datetime last_seen_at
        uuid last_run_id FK
    }
    STATISTIC_VERSION {
        bigint id PK
        bigint statistic_id FK
        integer version
        decimal value "Nullable"
        string source_status
        string fingerprint
        uuid run_id FK
        datetime created_at
    }
    IMPORT_SOURCE {
        bigint id PK
        uuid run_id FK
        string code
        string url
        string sha256
        string reference_period
        datetime collected_at
    }
    STATISTIC_OBSERVATION {
        bigint id PK
        bigint statistic_id FK
        bigint statistic_version_id FK
        bigint source_id FK
        uuid run_id FK
        string source_columns
        string transformation_version
        datetime collected_at
    }
    DATA_COVERAGE {
        bigint id PK
        uuid run_id FK
        string level
        string parent_code "Logical official code, not a foreign key"
        string status
        integer record_count
        string message
    }
```

Geography is unique by code, level and reference year. Category is unique by indicator and category code.
Statistic is unique by integration, geography, category and period. Version is unique by statistic and
version number; observation by statistic and run; source by run and source code. Statistical versions,
observations, source artifacts and coverage evidence are append-only. Geography metadata is shared,
while values and lineage are scoped through the owning integration. See [IBGE semantics and coverage](ibge-integration.md).

## Map spatial references

```mermaid
erDiagram
    GEOGRAPHY ||--o| GEOGRAPHY_MAP_REFERENCE : locates
    GEOGRAPHY_MAP_REFERENCE {
        bigint id PK
        bigint geography_id FK,UK
        decimal latitude "Nullable, paired with longitude"
        decimal longitude "Official administrative seat"
        decimal area_km2 "Nullable, positive territorial area"
        string coordinate_kind
        integer reference_year
        json provenance "Official coordinate and area URLs plus SHA-256"
    }
```

Spatial metadata is shared by geography, level and reference year. Owned statistical values remain
in `STATISTIC`; the read-only [audience map](audience-map.md) joins them without copying or rewriting
observations. Paired-coordinate and positive-area constraints apply at database level.
