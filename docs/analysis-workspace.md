# Analysis workspace and performance delivery

Open the [map](http://127.0.0.1:8012/map/) or the
[analysis workspace](http://127.0.0.1:8012/map/workspace.html). Both are served by the independent
`audience-map` container. Swagger remains the only interactive API credential form; tokens are
memory-only and navigation between pages requires authorization again.

## Delivered capabilities

| Improvement | Implemented behavior |
| --- | --- |
| Visible-area queries | Optional viewport mode sends validated bounding coordinates after zoom/pan, with a debounce. Coordinates are filtered in SQL before loading age bands. |
| Bubble grouping | Screen-grid clusters expand with zoom. Count is summed; density is summed cohort divided by summed territorial area, never a sum or average of densities. Missing values remain unknown. |
| Distinct map measures | Color by cohort count, source-population share, density, or uploaded municipal ticket evidence. Bubble size always describes the selected census cohort. |
| Query optimization | Scope indexes, latitude/longitude lookup and PostGIS GiST index; bounded hot-query cache with owner, credential version, filters, reference year and source-version/collection signatures. Read-only requests no longer acquire the global write/import coordinator. |
| Saved scenarios | Owned filters, revisions, optional watching, immutable snapshots, archival and comparison of 2–5 captures. Viewport is excluded from a saved demographic scope. |
| Venue simulations | Proposed coordinates, distance and road-time limits can be saved as separate scenarios and compared without creating fictitious events. |
| Sales origins and editions | Validated CSV import, per-event/edition identity, duplicate-file detection, correction versions, municipal summaries and comparisons between editions. Ticket counts are not unique-buyer counts. |
| Opportunity hypotheses | Compare a scenario against uploaded municipal tickets, prioritizing large cohorts without uploaded sales evidence. Absence of records is explicitly not proof of zero sales or demand. No conversion/demand forecast is manufactured. |
| Commercial annotations | Owned notes, optionally tied to a scenario or imported geography, with an audit record. |
| Reports | Standalone HTML with a captured SVG map, tables, filters, coverage and limitations; complete JSON with source IDs/versions and provenance. HTML can be printed to PDF. |
| Local alerts | Independent `analysis-monitor` container checks watched scenarios for owned source changes. Alerts are deduplicated and remain inside the workspace; no emails or external messages are sent. |
| Quality | Missing observations, coordinates/areas, source collection dates and recent import outcomes. A new collection does not change Census 2022's reference year. |
| Local road accessibility | Separate, pinned OSRM Docker engine, regional road graph, car-profile times from locality seats to a selected event/venue; unavailable coverage stays unknown. |

Source watching is intentionally conservative: a changed owned source version or collection record can
raise an alert even if the changed item falls outside the scenario's selected population. Capture a
new snapshot to inspect the change; existing evidence is never overwritten.

## Sales CSV

Choose an owned event and edition in the workspace, then download the template and supply a UTF-8 CSV:

```csv
sale_id,sold_on,municipality_code,tickets,revenue
order-line-001,2026-11-01,3550308,2,120.00
order-line-002,2026-11-02,,1,80.00
```

- `sale_id` is an opaque order-line identifier, unique inside the event and edition. Do not use names,
  email addresses or other personal profiles as identifiers.
- `sold_on` is an ISO date between 2000 and today.
- `municipality_code` is the declared ticket/buyer-origin municipality's seven-digit IBGE code, not
  the venue municipality. Blank or not-yet-imported origins remain unresolved and visible in quality.
- `tickets` is an integer from 0 to 1000000. `revenue` is the corrected nonnegative BRL line total,
  with decimal point and up to two decimals. A corrected cancellation can set both values to zero.
- Limits: 5 MiB and 10000 rows. Unknown columns, malformed values and duplicate line IDs in one file
  reject the whole batch before changes are committed. Raw files, filenames and personal profiles
  are not stored; file SHA-256 and normalized, versioned records are retained.

Repeated identical files are idempotent per API account, event and edition. Changed lines append
`SaleVersion`; unchanged lines do not. Missing lines are retained, so a partial file cannot silently
erase sales. Inserts/updates and versions are batched rather than issuing several queries per CSV row.

Permissions are granular: `sales:read/write`, `scenarios:read/write/edit/delete`, `reports:read`, plus
`events:read` and `demographics:read` where those sources are used. Existing ordinary roles do not gain
these permissions automatically. The protected master API account has the full catalog.

## Local routing

The Docker engine is pinned to OSRM v26.11.0 by image digest. It has no public host port or application
credentials. `routing/data/` is ignored by Git and Docker builds. Data manifests retain upstream URL,
last-modified date, SHA-256, graph image, profile, coverage bounding box and OSM attribution.

This machine provides about 8 GiB to Docker. The initially prepared graph is a compact Rio de Janeiro
extract from BBBike/OpenStreetMap, which was processed and tested locally. It is **not national routing
coverage** and does not cover São Paulo. Outside that graph, no driving time is invented. Public-road
accessibility is an estimate without live traffic, parking or public-transport schedules; administrative
seats are used as origins, not individual homes. Road-time and straight-line-radius filters are separate.

Configuration:

```json
"routing": {"enabled": true, "region": "rio-de-janeiro"}
```

Run `python start.py --prepare-routing` to download/process the configured graph before startup.
Other supported extracts are `sudeste` (approximately 823 MB compressed at verification) and `brazil`
(approximately 2 GB compressed). Preprocessing requires substantially more memory than download size;
national preparation is unsuitable for the present 8 GiB Docker allocation. Increase resources before
selecting a larger region. For an explicitly chosen preprocessing memory limit, use
`python routing/prepare.py --region brazil --memory 32g`, then restart `start.py` with matching config.
The application remains usable if routing is disabled or a graph is not prepared; road-time filters
then report unknown coverage. Graphs are reused rather than downloaded on every startup.

Sources: [OSRM documentation](https://github.com/Project-OSRM/osrm-backend),
[Rio extract](https://download.bbbike.org/osm/bbbike/RiodeJaneiro/),
[Geofabrik Brazil](https://download.geofabrik.de/south-america/brazil.html),
[PostGIS indexed radius queries](https://postgis.net/docs/ST_DWithin.html).

JSON and static frontend assets are compressed by Nginx when the client accepts gzip. Browser cache
policies remain `no-store`; compression does not weaken ownership or token checks.

## Relational storage and measured performance

`Sale` links to its API account, event, edition and optional geography; `SalesUpload` records batch
provenance; `SaleVersion` is append-only. `AnalysisScenario`, append-only `ScenarioSnapshot`,
`AnalysisNote` and deduplicated `AnalysisAlert` preserve analysis evidence. Migrations 0018–0020 add
these tables, history protections, permissions and indexes. PostgreSQL remains major version 17,
now using `postgis/postgis:17-3.7-alpine`. A local pre-upgrade database backup was created before deployment.
Existing API credentials, encrypted provider tokens, events and statistical history were preserved.

On the same local 430-municipality query, five executions measured a warm median of approximately
202.43 ms before optimization and 36.09 ms in the isolated optimized stack (about 82% lower latency,
5.6× faster in this measurement). This measures server-side query/render computation, not network or
browser time, and is not a production SLA. Repeat with `qa/benchmark_map.py` inside manage.py shell;
it prints timing/query counts, never credentials or source records. Initial uncached queries remain
more expensive. Cache size is bounded to 32 entries and 120 seconds and cannot bypass authorization.

Validation: 130 tests on PostgreSQL/PostGIS, real-browser map/workspace flows, source-preserving exports,
mobile layouts and a real local road-time query covering 11 locations. Sales and event fixtures were
created only in the disposable QA stack; the main environment contains no synthetic sales.

## Data dependencies that remain explicit

Current IBGE imports contain age populations and locality income summaries, not a joint population
distribution by individual age and income. No exact cross-classification is claimed. Sales insights
become evidence-based only after actual files are uploaded. Campaign spend/attribution and public
transport schedules are not among the supplied sources, so ROI or transit-time reports are not invented.
These are data prerequisites, distinct from the delivered upload, scenario and report infrastructure.
