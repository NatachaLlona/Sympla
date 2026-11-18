import {apiSession} from './session.js';
const $ = id => document.getElementById(id), NS = 'http://www.w3.org/2000/svg';
const format = value => value === null || value === undefined ? 'Unavailable' : new Intl.NumberFormat('en-US', {maximumFractionDigits: 2}).format(value);
const levelNames = {city: 'Municipalities', district: 'Districts', neighborhood: 'Neighborhoods'};
const state = {options: null, events: [], geographies: [], points: [], result: null, serial: 0, busy: false};
let scale = 1, tx = 0, ty = 0, bounds = null, drag = null, moved = false;
let viewportTimer;
function currentBbox() {
  const inverse = (x, y) => [(x-30)/20-75, (2*Math.atan(Math.exp(Math.log(Math.tan(Math.PI/4+6*Math.PI/360))-(y-40)/20*Math.PI/180))-Math.PI/2)*180/Math.PI];
  const a = inverse(-tx/scale,-ty/scale), b = inverse((1100-tx)/scale,(950-ty)/scale);
  return [Math.max(-180,a[0]),Math.max(-85,b[1]),Math.min(180,b[0]),Math.min(85,a[1])].join(',');
}
function scheduleViewport() { clearTimeout(viewportTimer); if ($('viewport').checked && state.result) viewportTimer = setTimeout(() => search(true), 450); }
function renderBubbles() {
  const selectedMetric=$('color-metric').value;
  $('legend-title').textContent=selectedMetric==='sales'?'Uploaded tickets · gray: no record':(state.result?.query.estimate?'Estimated ':'Confirmed lower-bound ')+(selectedMetric==='count'?'cohort count':selectedMetric==='share'?'cohort share · %':'cohort / km²');
  const ticks=selectedMetric==='sales'?['0–9','10–49','50–199','200–999','1000+']:selectedMetric==='count'?['<1k','1–10k','10–50k','50–100k','100k+']:selectedMetric==='share'?['<1%','1–3%','3–5%','5–10%','10%+']:['<1','1–5','5–25','25–100','100+'];
  [...document.querySelectorAll('.legend-ticks span')].forEach((item,index)=>item.textContent=ticks[index]);
  const container = $('map-bubbles'); container.replaceChildren();
  if (!state.points.length) return;
  const groups = new Map(), cluster = $('cluster').checked;
  for (const row of state.points) {
    const p = project(row.longitude,row.latitude), key = cluster ? `${Math.floor((p[0]*scale+tx)/48)}:${Math.floor((p[1]*scale+ty)/48)}` : row.geography.code;
    if (!groups.has(key)) groups.set(key, []); groups.get(key).push(row);
  }
  const maxCount = Math.max(1,...[...groups.values()].map(rows=>rows.reduce((sum,row)=>sum+count(row),0)));
  for (const rows of groups.values()) {
    const points = rows.map(row=>project(row.longitude,row.latitude));
    const total = rows.reduce((sum,row)=>sum+count(row),0), area = rows.reduce((sum,row)=>sum+(row.area_km2||0),0);
    const metric=$('color-metric').value, population=rows.reduce((sum,row)=>sum+(row.source_age_total||0),0);
    const unknown = rows.some(row=>row.match==='incomplete_coverage'||(metric==='density'&&!row.area_km2)||(metric==='share'&&!row.source_age_total)||(metric==='sales'&&state.sales?.[row.geography.code]===undefined));
    const confirmed=rows.reduce((sum,row)=>sum+(row.estimated_count!==null?row.estimated_count:row.lower_bound),0);
    const value = unknown ? null : metric==='sales'?rows.reduce((sum,row)=>sum+Number(state.sales?.[row.geography.code]||0),0):metric==='count'?confirmed:metric==='share'?confirmed/population*100:confirmed/area;
    const radius = Math.max(4,Math.sqrt(total/maxCount)*27), cx = points.reduce((sum,p)=>sum+p[0],0)/points.length, cy=points.reduce((sum,p)=>sum+p[1],0)/points.length;
    const node = svg('circle',{cx,cy,r:radius/scale,class:`map-bubble ${rows.length>1?'map-cluster ':''}${densityClass(value)}`,tabindex:'0',role:'button'});
    const label = rows.length>1 ? `${rows.length} locations · cohort ${format(total)} · ${metric} ${format(value)}. Select to zoom.` : `${rows[0].geography.name}: cohort ${interval(rows[0].lower_bound,rows[0].upper_bound)}`;
    node.setAttribute('aria-label',label); node.dataset.radius=radius;
    const title=svg('title'); title.textContent=label; node.append(title);
    const choose=()=>{ if(rows.length===1) details(rows[0]); else {fit([Math.min(...points.map(p=>p[0])),Math.min(...points.map(p=>p[1])),Math.max(...points.map(p=>p[0])),Math.max(...points.map(p=>p[1]))],160);scheduleViewport();} };
    node.addEventListener('click',()=>{if(!moved) choose();}); node.addEventListener('keydown',event=>{if(['Enter',' '].includes(event.key)){event.preventDefault();choose();}});
    container.append(node);
  }
}
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
  renderBubbles();
  for (const node of $('event-marker').children) node.setAttribute('r', 9/scale);
}
function zoom(factor, x = 550, y = 475) {
  const next = Math.min(55, Math.max(.6, scale*factor)), ratio = next/scale;
  tx = x-(x-tx)*ratio; ty = y-(y-ty)*ratio; scale = next; transform(); scheduleViewport();
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
function endDrag() { if (drag && moved) scheduleViewport(); drag = null; }
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
  state.sales = null; if($('color-metric').value==='sales') $('color-metric').value='density';
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
function densityClass(value) { const limits=$('color-metric').value==='sales'?[10,50,200,1000]:$('color-metric').value==='count'?[1000,10000,50000,100000]:$('color-metric').value==='share'?[1,3,5,10]:[1,5,25,100]; return value===null?'density-unknown':`density-${value<limits[0]?0:value<limits[1]?1:value<limits[2]?2:value<limits[3]?3:4}`; }
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
  state.sales=null;if($('color-metric').value==='sales')$('color-metric').value='density';
  state.lastQuery = {integration_id: result.integration_id, ...result.query, ...result.income_filter};
  delete state.lastQuery.minimum; delete state.lastQuery.maximum; delete state.lastQuery.metric;
  Object.assign(state.lastQuery, {income_min: result.income_filter.minimum ?? '', income_max: result.income_filter.maximum ?? '', income_metric: result.income_filter.metric});
  if (result.event?.id) state.lastQuery.event_id = result.event.id;
  if (result.event && result.event.id === null) Object.assign(state.lastQuery, {venue_lat: result.event.latitude, venue_lon: result.event.longitude});
  if (result.radius_km !== null) state.lastQuery.radius_km = result.radius_km;
  if (result.max_travel_minutes !== null) state.lastQuery.max_travel_minutes = result.max_travel_minutes;

  state.result = result; state.points = result.results; $('map-bubbles').replaceChildren(); $('event-marker').replaceChildren(); $('location-detail').hidden = true;
  const maxCount = Math.max(1, ...state.points.map(count));
  renderBubbles();
  if (result.event?.latitude !== null && result.event?.latitude !== undefined) {
    const [cx, cy] = project(result.event.longitude, result.event.latitude), pin = svg('circle', {cx, cy, r: 9/scale, class: 'event-pin'}), title = svg('title'); title.textContent = result.event.name; pin.append(title); $('event-marker').append(pin);
  }
  $('mapped').textContent = format(result.count); $('granularity').textContent = levelNames[result.query.level];
  $('map-title').textContent = `Brazil · ages ${result.query.age_min}–${result.query.age_max}`;
  $('map-subtitle').textContent = `${result.query.source_year} census → ${result.query.target_year} age alignment · ${result.event ? result.event.name : 'all selected locations'}`;
  $('result-badge').textContent = `${result.count} / ${result.candidate_count} locations`;
  const c = result.coverage;
  $('coverage-note').textContent = `${result.count} mapped. ${c.missing_coordinates} eligible locations have no official seat coordinates; ${c.missing_area} mapped locations have no area. ${c.excluded_by_income} excluded by locality income; ${c.excluded_by_distance} excluded by distance. ${c.missing_income} source locations have unavailable income. No missing values are treated as zero.`;
  if(result.max_travel_minutes!==null)$('coverage-note').textContent+=` Road extract: ${result.routing.region||'not prepared'} · ${result.routing.status}. ${c.unroutable_locations} locations have unknown road time; ${c.excluded_by_travel_time} exceed the limit. OSM car profile, no live traffic.`;
  const list = $('location-list'); list.replaceChildren();
  for (const row of [...state.points].sort((a,b) => count(b)-count(a)).slice(0, 20)) {
    const button = element('button'); button.type = 'button'; button.append(element('span', row.geography.name), element('strong', row.estimated_count !== null ? `≈ ${format(row.estimated_count)}` : interval(row.lower_bound, row.upper_bound)));
    button.addEventListener('click', () => { details(row); const p = project(row.longitude, row.latitude); fit([p[0]-3,p[1]-3,p[0]+3,p[1]+3], 220); $('location-detail').scrollIntoView({behavior: 'smooth', block: 'nearest'}); }); list.append(button);
  }
  if (!result.count) list.append(element('p', 'No mappable data matches these filters. Try a city-level source, remove the income or distance filters, or import the required geography.', 'field-help'));
  const points = state.points.map(row => project(row.longitude, row.latitude));
  if (result.event?.latitude !== null && result.event?.latitude !== undefined) points.push(project(result.event.longitude, result.event.latitude));
  if (state.preserveView) return message(`${result.count} visible locations mapped. Viewport filtering does not change the census granularity.`);
  if (result.event && points.length) fit([Math.min(...points.map(p=>p[0])),Math.min(...points.map(p=>p[1])),Math.max(...points.map(p=>p[0])),Math.max(...points.map(p=>p[1]))], 130); else fit(bounds);
  const incomplete = state.points.filter(row => row.match === 'incomplete_coverage').length;
  message(result.count ? `${result.count} locations mapped. ${incomplete} have incomplete age coverage. Income filters select localities, not individual people. Census births, deaths and migration are not projected.` : 'No mappable observations match the selected filters. Coverage details below explain omitted locations.');
}
async function search(viewportOnly = false) {
  if (state.busy || !$('map-form').reportValidity()) return;
  if (Number($('age-max').value) < Number($('age-min').value)) { message('To age must be greater than or equal to From age.', true); return; }
  const serial = ++state.serial; state.busy = true; $('apply').disabled = true; $('apply').textContent = 'Mapping…';
  const box = $('viewport').checked ? currentBbox() : '';
  try {
    const result = await api.get('/api/v1/demographics/map/', {integration_id: $('integration').value, source_year: 2022,
      target_year: $('target-year').value, age_min: $('age-min').value, age_max: $('age-max').value, level: $('level').value,
      state_code: $('state').value, event_id: $('workflow').value === 'event' ? $('event').value : '', radius_km: $('radius').disabled ? '' : $('radius').value,
      income_metric: $('income-metric').value, income_min: $('income-min').value, income_max: $('income-max').value,
      estimate: $('estimate').checked ? 'true' : 'false',
      venue_lat: $('workflow').value === 'venue' ? $('venue-lat').value : '', venue_lon: $('workflow').value === 'venue' ? $('venue-lon').value : '',
      bbox: box, max_travel_minutes: $('travel-minutes').value});
    if (serial === state.serial) { state.preserveView = viewportOnly || !!box; draw(result); }
  } catch (error) { if (serial === state.serial) { clearResults(); message(error.message, true); } }
  finally { state.busy = false; $('apply').disabled = !state.options; $('apply').textContent = 'Update map →'; if(box && $('viewport').checked && box!==currentBbox()) scheduleViewport(); }
}
$('map-form').addEventListener('submit', event => { event.preventDefault(); search(); });
$('target-year').addEventListener('input', ageHelp); $('event').addEventListener('change', eventChanged);
$('integration').addEventListener('change', () => sourceChanged().catch(error => message(error.message, true)));
$('reset').addEventListener('click', () => { defaults(); eventChanged(); clearResults(); fit(bounds); });
$('cluster').addEventListener('change', renderBubbles);
$('color-metric').addEventListener('change',async()=>{
  if($('color-metric').value==='sales'){
    try{if(!state.result?.event?.id||state.result.query.level!=='city')throw new Error('Choose an event and a city-level source before mapping uploaded ticket evidence.');
      const body=await api.get('/api/v1/sales/summary/',{event_id:state.result.event.id});state.sales=Object.fromEntries(body.by_origin.map(row=>[row.municipality_code,row.tickets]));message('Color shows uploaded tickets; bubble size remains the census cohort. Gray means no uploaded origin record, not zero sales or zero demand. Ticket buyers are not matched to the selected age/income group.');
    }catch(error){$('color-metric').value='density';message(error.message,true);}
  }renderBubbles();
});
$('workflow').addEventListener('change', () => { const venue = $('workflow').value === 'venue'; $('venue-fields').hidden = !venue; $('event').disabled = $('workflow').value !== 'event'; if (venue) { $('radius').disabled=false; $('radius').value='100'; } else if($('workflow').value==='region'){$('radius').disabled=true;$('radius').value='';}else eventChanged(); });
$('save-scenario').addEventListener('click', async () => {
  if (!state.lastQuery || !state.result) return message('Apply a map search before saving a scenario.',true);
  try { const saved=await api.send('/api/v1/analysis/scenarios/',{method:'POST',body:JSON.stringify({name:$('scenario-name').value,filters:state.lastQuery,watch:true})}); message(`Scenario ${saved.id} captured. Open Analysis workspace to compare, annotate or export.`); }
  catch(error){message(error.message,true);}
});
defaults(); outlines().catch(error => message(error.message, true));
