# Integration delivery status

## Demographic frontend

National scope added: 430 municipalities covering the 27 capitals and their official metropolitan
regions/RIDEs, based on corrected IBGE composition 2025. Municipal demographic measurements retain
reference year 2022. The local import created 6,450 observations without missing values, while retaining
coverage warnings where official age and basic population totals differ. Validation: 107 PostgreSQL tests.

The `frontend` container provides a read-only demographic explorer, source lineage and CSV export.
It uses the existing API and `demographics:read` permission; provider integrations remain independent.
Calendar-year cohort alignment advances the published age bands without overwriting census values
or inferring post-census births. See [frontend behavior and validation](demographic-frontend.md).

## Sympla event integration: completed

The completed delivery covers API-account-scoped Sympla event imports, daily schedules and manual
synchronization, relational event storage, immutable content versions and import observations,
integration configuration CRUD, granular authorization and Docker/PostgreSQL startup.

The README, [entity-relationship diagrams](data-model.md) and [program flowcharts](import-flow.md)
describe the delivered behavior. Validation included 67 PostgreSQL tests, a populated legacy-database
migration and the Docker startup/persistence checks. Existing API credentials and event history were preserved.

Delivery branch: `feat/sympla-integration`, integrated into `main`.

## IBGE data integration: initial implementation

Development branch: `feat/ibge-integration`, starting from the completed Sympla delivery in `main`.
The initial implementation imports Census 2022 population, age and income through an independent IBGE
container. Relational statistics, immutable lineage and explicit geographical coverage are documented in
[IBGE integration](ibge-integration.md). São Paulo uses official districts as an explicitly labeled fallback
when the official neighborhood product has no records; unavailable state income remains a reported gap.
