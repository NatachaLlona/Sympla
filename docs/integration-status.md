# Integration delivery status

## Sympla event integration: completed

The completed delivery covers API-account-scoped Sympla event imports, daily schedules and manual
synchronization, relational event storage, immutable content versions and import observations,
integration configuration CRUD, granular authorization and Docker/PostgreSQL startup.

The README, [entity-relationship diagrams](data-model.md) and [program flowcharts](import-flow.md)
describe the delivered behavior. Validation included 67 PostgreSQL tests, a populated legacy-database
migration and the Docker startup/persistence checks. Existing API credentials and event history were preserved.

Delivery branch: `feat/sympla-integration`, integrated into `main`.

## IBGE data integration: next development stage

Development branch: `feat/ibge-integration`, starting from the completed Sympla delivery in `main`.
IBGE connectors, datasets and endpoints have not been implemented. Their scope will be defined in the
next stage using the registered connector architecture and the existing authorization and lineage patterns.
