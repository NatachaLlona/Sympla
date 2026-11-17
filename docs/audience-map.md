# Audience map

Open `http://127.0.0.1:8012/map/`, or choose **Audience map** from the demographic explorer.
The independent `audience-map` module has its own directory, Dockerfile, Nginx server, image,
container, health check and configurable port (`audience_map.port`, default 8012). `start.py` builds
and starts it alongside the other modules. It shares the authenticated API and PostgreSQL database,
permissions and Swagger Authorize flow. Navigation to a new page requires authorization again; Bearer
tokens stay in page memory and are cleared on disconnect, expiry or reload. No credential form or
browser-native HTTP Basic challenge was added.

## Filters and rendering

- Select an owned event, optionally limiting results to 25–500 km from its coordinates. Nationwide
  comparison is also available. Events require `events:read`; demographic searches require
  `demographics:read`. Events without valid coordinates remain selectable, but distance filtering is
  disabled and their positions are never guessed.
- Choose an age interval and analysis year. The existing calendar-year shift advances the observed
  Census 2022 cohort. Births after the census, mortality and migration are not modeled. Partial source
  bands retain lower/upper bounds; the optional proportional estimate is explicit.
- Filter by locality mean or median monthly income of household responsible persons with income.
  Units are nominal BRL 2022. These summaries do **not** reveal the number of people jointly satisfying
  age and individual-income criteria. No joint population count or current salary is inferred.
- Choose an owned IBGE source, geography level and state. The national source covers 430 municipalities.
  Zoom changes the viewport; it does not manufacture smaller-area data or change geography level.

The SVG map supports zoom buttons, wheel zoom, pointer dragging and keyboard arrows/+/-/Home.
Colored bubbles represent aligned census cohort density: count divided by full official territorial
area in km². With partial bands, the default color uses the confirmed lower bound. An explicitly
enabled proportional estimate changes the legend and calculation. Incomplete cohorts and missing
areas use gray. Bubble size encodes cohort count with a minimum visible radius; overlapping bubbles
are not summed or interpreted as a heatmap. They remain individually selectable after zooming.

Anchors are official municipal or district seats, not household coordinates or uniform population
distributions. Event distance is a great-circle distance to those seats; it is neither travel distance
nor an intersection of the event radius with municipal polygons. Density is not recalculated over a
circle around the event. Counts are never reduced by an assumed share within that circle.

Location details expose bounds/estimates, territorial area, locality income, source statistic IDs and
versions, coordinate kind, source URLs and SHA-256. Missing coordinates, missing areas, unavailable
income and filter exclusions are reported separately. Locations without a published, unambiguous
official seat cannot be drawn; neighborhood/district points are never placed at a municipal center
as a substitute. The largest 20 results also have keyboard-accessible detail buttons.

## Relational storage and provenance

Migration `0017_geographymapreference` adds a one-to-one spatial reference to `Geography`: paired
numeric latitude/longitude, positive territorial area, coordinate kind, reference year and provenance.
Database constraints reject unpaired/out-of-range coordinates and nonpositive areas. Existing
statistics, histories, events, API credentials and provider modules are preserved.

`start.py` runs the reference setup after migrations. New IBGE imports attach available references
when a geography is first encountered. For a manual refresh, run:

```text
docker exec sympla-api-1 python manage.py configure_map_reference
```

The pinned sources are:

- [IBGE state boundaries, 2022](https://geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/malhas_municipais/municipio_2022/Brasil/BR/BR_UF_2022.zip).
- [IBGE Localidades do Brasil, 2022 edition](https://geoftp.ibge.gov.br/organizacao_do_territorio/estrutura_territorial/localidades/Localidades_do_Brasil/2022/Localidades_Brasil_shp.zip), with official city/district seats.
- The same pinned Census 2022 aggregate base files used by the IBGE connector, specifically their
  `AREA_KM2` fields. Official territorial areas are not calculated from the simplified display outline.

Display boundaries are simplified to approximately 0.025 degrees for a small offline GeoJSON.
Production reads bundled assets and relational records, requiring no external tiles, map account,
geocoder, browser network access to IBGE, or third-party JavaScript library. To reproduce assets,
build `qa/map-assets.Dockerfile`, then run it with the repository mounted at `/work`. Downloads are
cached under ignored `.qa-local/map-sources`; the generated manifests retain every source URL/hash.
PyShp is used only by this reproducibility tool, not by application containers.

## API and validation

`GET /api/v1/demographics/map/` accepts the documented cohort filters plus `event_id`, `radius_km`,
`income_metric`, `income_min` and `income_max`. It is owner-scoped and read-only, with a maximum of
3000 candidate locations per request. Swagger documents its semantics and permission requirements.

Validation passed 116 PostgreSQL tests and isolated Chromium checks for 27 state outlines, 430 real
municipal bubbles, Swagger authorization, zoom, locality income filtering, event proximity, partial
bands, post-census birth gaps, source details, mobile overflow and disconnect. The event used by
browser tests is an explicitly named fixture in the disposable QA stack; production events are untouched.

After `python qa/prepare_frontend_qa.py`, build `qa/browser.Dockerfile` and run its image with
`--network container:sympla-startup-qa-frontend-1`, mounting an artifacts directory at `/artifacts`,
and command `node /qa/map-test.cjs`. Run once through the explorer's proxy and once with
`--network container:sympla-startup-qa-audience-map-1` to verify both entry points.

The explorer forwards `/map/` to the independent map container and redirects the older `/map.html`
link there. On the map container, `/` redirects to `/map/`; `/explorer/` provides navigation back to
the explorer. Map assets are served only from `/map/`. Shared typography/CSS primitives and favicon
are copied into the map image at build time. The map page and its API authorization work without the
explorer container; only navigation to the explorer needs that service. No database/provider secrets
are mounted in either frontend module.
