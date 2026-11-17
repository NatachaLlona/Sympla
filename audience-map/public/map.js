import {apiSession} from './session.js';
const $ = id => document.getElementById(id), NS = 'http://www.w3.org/2000/svg';
const format = value => value === null || value === undefined ? 'Unavailable' : new Intl.NumberFormat('en-US', {maximumFractionDigits: 2}).format(value);
const levelNames = {city: 'Municipalities', district: 'Districts', neighborhood: 'Neighborhoods'};
const state = {options: null, events: [], geographies: [], points: [], result: null, serial: 0, busy: false};
let scale = 1, tx = 0, ty = 0, bounds = null, drag = null, moved = false;
function element(tag, text, cls) { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (cls) node.className = cls; return node; }
function svg(tag, attrs = {}) { const node = document.createElementNS(NS, tag); for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value); return node; }
function message(text, error = false) { $('notice').textContent = text; $('notice').className = error ? 'notice error' : 'notice success'; }
function options(id, rows, empty) {
  const node = $(id); node.replaceChildren();
  if (empty !== undefined) { const item = element('option', empty); item.value = ''; node.append(item); }
  for (const row of rows) { const item = element('option', row.name); item.value = row.id ?? row.code; node.append(item); }
}
function project(lon, lat) { return [(Number(lon)+75)*20+30, (Math.log(Math.tan(Math.PI/4+6*Math.PI/360))-Math.log(Math.tan(Math.PI/4+Number(lat)*Math.PI/360)))*20*180/Math.PI+40]; }
function transform() {
  $('map-world').setAttribute('transform', `translate(${tx} ${ty}) scale(${scale})`);
  for (const node of $('map-bubbles').children) node.setAttribute('r', Number(node.dataset.radius)/scale);
  for (const node of $('event-marker').children) node.setAttribute('r', 9/scale);
}
function zoom(factor, x = 550, y = 475) {
  const next = Math.min(55, Math.max(.6, scale*factor)), ratio = next/scale;
  tx = x-(x-tx)*ratio; ty = y-(y-ty)*ratio; scale = next; transform();
}
function fit(box, padding = 100) {
  if (!box) return;
  const [x1, y1, x2, y2] = box;
  scale = Math.min(35, Math.max(.6, Math.min((1100-padding*2)/Math.max(x2-x1, 5), (950-padding*2)/Math.max(y2-y1, 5))));
  tx = 550-(x1+x2)/2*scale; ty = 475-(y1+y2)/2*scale; transform();
}
function screen(event) { const point = new DOMPoint(event.clientX, event.clientY); return point.matrixTransform($('brazil-map').getScreenCTM().inverse()); }
$('zoom-in').addEventListener('click', () => zoom(1.5)); $('zoom-out').addEventListener('click', () => zoom(1/1.5)); $('fit-brazil').addEventListener('click', () => fit(bounds));
$('brazil-map').addEventListener('wheel', event => { event.preventDefault(); const p = screen(event); zoom(event.deltaY < 0 ? 1.15 : 1/1.15, p.x, p.y); }, {passive: false});
$('brazil-map').addEventListener('pointerdown', event => { if (event.button !== 0) return; const p = screen(event); drag = {x: p.x, y: p.y, tx, ty, pointer: event.pointerId}; moved = false; });
$('brazil-map').addEventListener('pointermove', event => { if (!drag || drag.pointer !== event.pointerId) return; const p = screen(event); if (Math.abs(p.x-drag.x)+Math.abs(p.y-drag.y) > 5) { moved = true; $('brazil-map').setPointerCapture(event.pointerId); } tx = drag.tx+p.x-drag.x; ty = drag.ty+p.y-drag.y; transform(); });
function endDrag() { drag = null; }
$('brazil-map').addEventListener('pointerup', endDrag); $('brazil-map').addEventListener('pointercancel', endDrag);
$('brazil-map').addEventListener('keydown', event => {
  if (event.key === '+' || event.key === '=') zoom(1.5);
  else if (event.key === '-') zoom(1/1.5);
  else if (event.key === 'Home') fit(bounds);
  else if (event.key.startsWith('Arrow')) { tx += event.key === 'ArrowLeft' ? 50 : event.key === 'ArrowRight' ? -50 : 0; ty += event.key === 'ArrowUp' ? 50 : event.key === 'ArrowDown' ? -50 : 0; transform(); }
  else return;
  event.preventDefault();
});
async function outlines() {
  const response = await fetch('/map/data/brazil-states-2022.geojson', {credentials: 'omit'});
  if (!response.ok) throw new Error('The bundled Brazil outline is unavailable.');
  const data = await response.json(), all = [];
  for (const feature of data.features) {
    const rings = feature.geometry.coordinates.map(ring => ring.map(point => project(...point)));
    all.push(...rings.flat());
    const path = svg('path', {d: rings.map(ring => 'M'+ring.map(point => point.join(',')).join('L')+'Z').join(''), class: 'state-outline'});
    path.append(svg('title')); path.firstChild.textContent = `${feature.properties.name} (${feature.properties.abbr})`;
    $('state-outlines').append(path);
  }
  bounds = [Math.min(...all.map(p => p[0])), Math.min(...all.map(p => p[1])), Math.max(...all.map(p => p[0])), Math.max(...all.map(p => p[1]))]; fit(bounds);
}
function clearResults() {
  state.points = []; state.result = null; $('map-bubbles').replaceChildren(); $('event-marker').replaceChildren();
  $('location-list').replaceChildren(element('p', 'Apply filters to load matching locations.', 'field-help'));
  $('location-detail').hidden = true; $('mapped').textContent = '—'; $('result-badge').textContent = 'No search results';
  $('coverage-note').textContent = 'No active results. Only locations with official coordinates can be drawn.';
  $('map-subtitle').textContent = 'Choose filters to see the imported data.';
}
function ageHelp() {
  const delta = Number($('target-year').value)-2022;
  $('age-help').textContent = `Census 2022 → ${$('target-year').value}: +${delta} calendar years. Post-census births are not covered.`;
  $('alignment').textContent = `2022 → ${$('target-year').value}`;
}
async function sourceChanged() {
  state.serial++; clearResults();
  const selected = state.options.integrations.find(row => row.id === $('integration').value);
  const available = (selected?.levels || []).filter(level => level !== 'state');
  options('level', available.map(code => ({code, name: levelNames[code]})));
  $('level').value = available.includes('city') ? 'city' : available[0] || '';
  const source = $('integration').value;
  const rows = await api.pages('/api/v1/geographies/', {integration_id: source});
  if (source !== $('integration').value) return;
  state.geographies = rows;
  options('state', rows.filter(row => row.level === 'state'), 'All imported states');
  // Filters use official codes, never internal geography identifiers.
  for (const item of $('state').options) if (item.value) item.value = rows.find(row => String(row.id) === item.value)?.code || item.value;
  $('apply').disabled = !available.length;
}
function eventChanged() {
  const selected = state.events.find(row => String(row.id) === $('event').value);
  const address = selected?.address;
  const valid = address && address.lat !== '' && address.lon !== '' && Number.isFinite(Number(address.lat)) && Number.isFinite(Number(address.lon)) && Math.abs(Number(address.lat)) <= 90 && Math.abs(Number(address.lon)) <= 180;
  $('radius').disabled = !valid; $('radius').value = valid ? '100' : '';
  $('event-help').textContent = !selected ? 'No event filter. All imported locations are eligible.' : valid ? 'Event selected. Distance uses administrative seats, not driving time.' : 'This event has no valid coordinates. Nationwide comparison remains available; no location is guessed.';
}
async function connected() {
  state.options = await api.get('/api/v1/demographics/explorer-options/');
  options('integration', state.options.integrations);
  const citySource = state.options.integrations.find(row => row.levels?.length === 1 && row.levels.includes('city'));
  if (citySource) $('integration').value = citySource.id;
  defaults();
  try { state.events = await api.pages('/api/v1/events/'); options('event', state.events, 'All locations · no event'); }
  catch (error) { state.events = []; options('event', [], 'Event access unavailable'); $('event-help').textContent = error.message; }
  if (!state.options.integrations.length) { message('No imported age data is available. Import an IBGE source before using the map.'); return; }
  await sourceChanged(); await search();
}
function disconnected() { state.serial++; clearResults(); $('apply').disabled = true; state.options = null; state.events = []; options('event', [], 'All locations · no event'); options('integration', [], 'Connect to load sources'); $('radius').disabled = true; message('Authorize through Swagger to load your owned events and demographic data.'); }
const api = apiSession(connected, disconnected);
function defaults() {
  const year = state.options?.current_year || Number(new Intl.DateTimeFormat('en', {year: 'numeric', timeZone: 'Europe/Lisbon'}).format(new Date()));
  $('target-year').max = $('target-year').value = year; $('age-min').value = year-2022; $('age-max').value = year-2022+4;
  $('income-min').value = $('income-max').value = ''; $('estimate').checked = false; $('income-metric').value = 'responsible_income_mean';
  $('event').value = ''; $('radius').value = ''; $('radius').disabled = true; $('state').value = ''; ageHelp();
}
function count(row) { return row.estimated_count ?? row.exact_count ?? row.lower_bound; }
function density(row) { return row.match === 'incomplete_coverage' ? null : row.density_estimate ?? row.density_lower; }
function densityClass(value) { return value === null ? 'density-unknown' : `density-${value < 1 ? 0 : value < 5 ? 1 : value < 25 ? 2 : value < 100 ? 3 : 4}`; }
function interval(low, high) { return low === high && low !== null ? format(low) : `${format(low)}–${high === null ? 'unknown' : format(high)}`; }
function details(row) {
  const panel = $('location-detail'); panel.replaceChildren(element('div', 'LOCATION DETAILS', 'eyebrow'), element('h2', row.geography.name));
  panel.append(element('p', `${levelNames[row.geography.level]} · IBGE ${row.geography.code} · ${row.coordinate_kind.replaceAll('_', ' ')}`));
  const grid = element('div', undefined, 'map-detail-grid');
  for (const [title, value] of [['Census cohort count', row.estimated_count !== null ? `≈ ${format(row.estimated_count)}` : interval(row.lower_bound, row.upper_bound)],
    ['Aligned cohort / km²', row.density_estimate !== null ? `≈ ${format(row.density_estimate)}` : interval(row.density_lower, row.density_upper)],
    ['Territorial area · km²', format(row.area_km2)], ['Locality income · BRL 2022', row.income.value === null ? 'Unavailable' : format(Number(row.income.value))]]) {
    const card = element('div'); card.append(element('small', title), element('strong', value)); grid.append(card);
  }
  panel.append(grid, element('p', `Band coverage: ${row.match.replaceAll('_', ' ')}. ${state.result.income_filter.metric.replaceAll('_', ' ')} is a locality summary, not an age/income cross-count.`));
  if (row.distance_km !== null) panel.append(element('p', `${format(row.distance_km)} km from the event to this administrative seat.`));
  panel.append(element('p', `Coordinates: ${row.latitude}, ${row.longitude}. Source reference: ${row.spatial_reference_year}.`));
  for (const [kind, source] of Object.entries(row.spatial_provenance)) if (source) {
    const paragraph = element('p', `${kind === 'area' ? 'Territorial area' : 'Official seat'} source: `), link = element('a', 'IBGE original file ↗');
    const url = new URL(source.url);
    if (url.protocol === 'https:' && ['ftp.ibge.gov.br', 'geoftp.ibge.gov.br'].includes(url.hostname)) { link.href = url.href; link.target = '_blank'; link.rel = 'noopener'; paragraph.append(link); }
    panel.append(paragraph, element('p', `SHA-256: ${source.sha256}`));
  }
  const bands = element('p', row.bands.filter(band => band.fully_included || band.count !== null).map(band => `${band.source_band}: ${format(band.count)} (statistic ${band.statistic_id}, version ${band.version})`).join(' · '));
  panel.append(element('h3', 'Original census bands'), bands);
  if (row.income.statistic_id) panel.append(element('p', `Income statistic ${row.income.statistic_id}, version ${row.income.version}.`));
  panel.hidden = false;
}
function draw(result) {
  state.result = result; state.points = result.results; $('map-bubbles').replaceChildren(); $('event-marker').replaceChildren(); $('location-detail').hidden = true;
  const maxCount = Math.max(1, ...state.points.map(count));
  for (const row of [...state.points].sort((a,b) => count(b)-count(a))) {
    const [cx, cy] = project(row.longitude, row.latitude), radius = 4+Math.sqrt(count(row)/maxCount)*23;
    const node = svg('circle', {cx, cy, r: radius/scale, class: `map-bubble ${densityClass(density(row))}`, tabindex: '0', role: 'button', 'aria-label': `${row.geography.name}: cohort ${interval(row.lower_bound, row.upper_bound)}`});
    node.dataset.radius = radius; const title = svg('title'); title.textContent = `${row.geography.name} · ${format(density(row))} aligned cohort / km²`; node.append(title);
    node.addEventListener('click', () => { if (!moved) details(row); }); node.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); details(row); } });
    $('map-bubbles').append(node);
  }
  if (result.event?.latitude !== null && result.event?.latitude !== undefined) {
    const [cx, cy] = project(result.event.longitude, result.event.latitude), pin = svg('circle', {cx, cy, r: 9/scale, class: 'event-pin'}), title = svg('title'); title.textContent = result.event.name; pin.append(title); $('event-marker').append(pin);
  }
  $('mapped').textContent = format(result.count); $('granularity').textContent = levelNames[result.query.level];
  $('map-title').textContent = `Brazil · ages ${result.query.age_min}–${result.query.age_max}`;
  $('map-subtitle').textContent = `${result.query.source_year} census → ${result.query.target_year} age alignment · ${result.event ? result.event.name : 'all selected locations'}`;
  $('legend-title').textContent = result.query.estimate ? 'Estimated cohort / km²' : 'Confirmed cohort lower bound / km²';
  $('result-badge').textContent = `${result.count} / ${result.candidate_count} locations`;
  const c = result.coverage;
  $('coverage-note').textContent = `${result.count} mapped. ${c.missing_coordinates} eligible locations have no official seat coordinates; ${c.missing_area} mapped locations have no area. ${c.excluded_by_income} excluded by locality income; ${c.excluded_by_distance} excluded by distance. ${c.missing_income} source locations have unavailable income. No missing values are treated as zero.`;
  const list = $('location-list'); list.replaceChildren();
  for (const row of [...state.points].sort((a,b) => count(b)-count(a)).slice(0, 20)) {
    const button = element('button'); button.type = 'button'; button.append(element('span', row.geography.name), element('strong', row.estimated_count !== null ? `≈ ${format(row.estimated_count)}` : interval(row.lower_bound, row.upper_bound)));
    button.addEventListener('click', () => { details(row); const p = project(row.longitude, row.latitude); fit([p[0]-3,p[1]-3,p[0]+3,p[1]+3], 220); $('location-detail').scrollIntoView({behavior: 'smooth', block: 'nearest'}); }); list.append(button);
  }
  if (!result.count) list.append(element('p', 'No mappable data matches these filters. Try a city-level source, remove the income or distance filters, or import the required geography.', 'field-help'));
  const points = state.points.map(row => project(row.longitude, row.latitude));
  if (result.event?.latitude !== null && result.event?.latitude !== undefined) points.push(project(result.event.longitude, result.event.latitude));
  if (result.event && points.length) fit([Math.min(...points.map(p=>p[0])),Math.min(...points.map(p=>p[1])),Math.max(...points.map(p=>p[0])),Math.max(...points.map(p=>p[1]))], 130); else fit(bounds);
  const incomplete = state.points.filter(row => row.match === 'incomplete_coverage').length;
  message(result.count ? `${result.count} locations mapped. ${incomplete} have incomplete age coverage. Income filters select localities, not individual people. Census births, deaths and migration are not projected.` : 'No mappable observations match the selected filters. Coverage details below explain omitted locations.');
}
async function search() {
  if (state.busy || !$('map-form').reportValidity()) return;
  if (Number($('age-max').value) < Number($('age-min').value)) { message('To age must be greater than or equal to From age.', true); return; }
  const serial = ++state.serial; state.busy = true; $('apply').disabled = true; $('apply').textContent = 'Mapping…';
  try {
    const result = await api.get('/api/v1/demographics/map/', {integration_id: $('integration').value, source_year: 2022,
      target_year: $('target-year').value, age_min: $('age-min').value, age_max: $('age-max').value, level: $('level').value,
      state_code: $('state').value, event_id: $('event').value, radius_km: $('radius').disabled ? '' : $('radius').value,
      income_metric: $('income-metric').value, income_min: $('income-min').value, income_max: $('income-max').value,
      estimate: $('estimate').checked ? 'true' : 'false'});
    if (serial === state.serial) draw(result);
  } catch (error) { if (serial === state.serial) { clearResults(); message(error.message, true); } }
  finally { state.busy = false; $('apply').disabled = !state.options; $('apply').textContent = 'Update map →'; }
}
$('map-form').addEventListener('submit', event => { event.preventDefault(); search(); });
$('target-year').addEventListener('input', ageHelp); $('event').addEventListener('change', eventChanged);
$('integration').addEventListener('change', () => sourceChanged().catch(error => message(error.message, true)));
$('reset').addEventListener('click', () => { defaults(); eventChanged(); clearResults(); fit(bounds); });
defaults(); outlines().catch(error => message(error.message, true));
