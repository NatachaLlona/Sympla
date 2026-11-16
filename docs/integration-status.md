# Integration delivery status

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
