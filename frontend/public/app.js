const $ = id => document.getElementById(id);
const state = {token: null, expires: 0, session: 0, options: null, geographies: [], query: null, result: null, busy: false, connection: null};
const format = value => new Intl.NumberFormat('en-US', {maximumFractionDigits: 2}).format(value);
const yearNow = Number(new Intl.DateTimeFormat('en', {year: 'numeric', timeZone: 'Europe/Lisbon'}).format(new Date()));
const levels = {state: 'States', city: 'Cities / municipalities', neighborhood: 'Neighborhoods', district: 'Districts'};
function el(tag, text, className) {
  const result = document.createElement(tag);
  if (text !== undefined && text !== null) result.textContent = String(text);
  if (className) result.className = className;
  return result;
}
function notice(message, kind = '') { $('notice').textContent = message; $('notice').className = `notice ${kind}`; }
function setOptions(id, rows, placeholder = null) {
  const select = $(id), previous = select.value;
  select.replaceChildren();
  if (placeholder !== null) { const item = el('option', placeholder); item.value = ''; select.append(item); }
  for (const row of rows) { const item = el('option', row.name); item.value = row.id ?? row.code; select.append(item); }
  if (rows.some(row => String(row.id ?? row.code) === previous)) select.value = previous;
  else if (rows.length === 1) select.value = rows[0].id ?? rows[0].code;
}
function resetResults() {
  state.result = null;
  $('results-body').replaceChildren();
  $('table-wrap').hidden = $('pagination').hidden = true;
  $('empty-state').hidden = false;
  $('export').disabled = true;
  $('metric-locations').textContent = $('metric-coverage').textContent = '—';
  $('results-title').textContent = 'Your next insight starts here.';
  $('results-subtitle').textContent = 'Select an age range and a geography to see the ranked results.';
}
function disconnect(message = 'Disconnected. Authorize through Swagger to start a new session.') {
  state.token = null; state.expires = 0; state.session += 1; state.query = null; state.options = null; state.geographies = [];
  $('connection-status').textContent = 'Not connected'; $('connection-status').className = 'connection-state';
  $('authorize').hidden = false; $('disconnect').hidden = true; $('search-button').disabled = true;
  $('coverage-panel').hidden = true; $('coverage-content').replaceChildren(); $('detail-dialog').close();
  setOptions('integration', [], 'Connect to load sources'); setOptions('state', [], 'All imported states'); setOptions('city', [], 'All imported cities');
  resetResults(); notice(message);
}
async function api(path, parameters = {}) {
  if (!state.token || Date.now() >= state.expires) { disconnect('Your API session expired. Authorize again through Swagger.'); throw new Error('API authorization is required.'); }
  const url = new URL(path, location.origin), session = state.session;
  for (const [key, value] of Object.entries(parameters)) if (value !== '' && value !== null && value !== undefined) url.searchParams.set(key, value);
  const response = await fetch(url, {headers: {Authorization: `Bearer ${state.token}`}, credentials: 'omit', cache: 'no-store'});
  if (session !== state.session) throw new Error('The API session changed.');
  let body;
  try { body = await response.json(); } catch (_) { throw new Error('The API is unavailable. Check the API container and try again.'); }
  if (response.status === 401) { disconnect('Your API session is invalid or expired. Authorize again through Swagger.'); throw new Error('API authorization is required.'); }
  if (!response.ok) throw new Error(response.status === 403 ? `This API account needs ${body.required_permission || 'demographics:read'} permission.` : body.message || body.error || `API request failed (${response.status}).`);
  return body;
}
async function allPages(path, parameters = {}, max = 10000) {
  const rows = [];
  for (let page = 1; ; page++) {
    const body = await api(path, {...parameters, page, page_size: 100});
    if (body.count > max) throw new Error('This scope is too large. Choose a narrower source or location.');
    rows.push(...body.results);
    if (rows.length >= body.count || !body.results.length) return rows;
  }
}
function syncYears() {
  const source = state.options?.source_years[0] || 2022, target = Number($('target-year').value) || yearNow, shift = target - source;
  $('source-year-display').textContent = source; $('target-year-display').textContent = target;
  $('year-shift').textContent = `+${shift} years →`;
  $('metric-shift').replaceChildren(document.createTextNode(`+${shift} `), el('em', 'years'));
  $('year-explanation').textContent = `Ages 0–4 in ${source} align to ages ${shift}–${shift + 4} in ${target}.`;
  $('age-help').textContent = `Selected ages map back by ${shift} calendar years. Ages below ${shift} are not covered by the ${source} census.`;
}
function presets() {
  const previous = $('age-preset').value, delta = Number($('target-year').value) - (state.options?.source_years[0] || 2022);
  const bands = state.options?.source_bands || [{age_min: 0, age_max: 4}, {age_min: 5, age_max: 9}, {age_min: 10, age_max: 14}];
  setOptions('age-preset', bands.filter(band => band.age_max !== null).map(band => ({id: `${band.age_min + delta}:${band.age_max + delta}`, name: `${band.age_min + delta}–${band.age_max + delta} in ${$('target-year').value} · ${band.age_min}–${band.age_max} in source`})), 'Custom age range');
  if ([...$('age-preset').options].some(item => item.value === previous)) $('age-preset').value = previous;
}
function updateCities() {
  setOptions('city', state.geographies.filter(row => row.level === 'city' && (!$('state').value || row.parent_code === $('state').value)).map(row => ({id: row.code, name: row.name})), 'All imported cities');
  $('city-label').hidden = $('city').disabled = $('level').value === 'state';
}
async function loadGeographies() {
  state.geographies = await allPages('/api/v1/geographies/', {integration_id: $('integration').value});
  const imported = state.options.integrations.find(row => row.id === $('integration').value)?.levels || [];
  if (imported.length && !imported.includes($('level').value)) $('level').value = imported.includes('city') ? 'city' : imported[0];
  setOptions('state', state.geographies.filter(row => row.level === 'state').map(row => ({id: row.code, name: row.name})), 'All imported states'); updateCities();
}
async function loadWorkspace() {
  state.options = await api('/api/v1/demographics/explorer-options/');
  $('target-year').max = $('target-year').value = state.options.current_year;
  const delta = state.options.current_year - (state.options.source_years[0] || 2022);
  $('age-min').value = delta; $('age-max').value = delta + 4;
  setOptions('integration', state.options.integrations); presets(); $('age-preset').value = `${delta}:${delta + 4}`; syncYears();
  if (!state.options.integrations.length) { notice('No imported age data is available for this API account. Import IBGE data before searching.'); return; }
  await loadGeographies(); $('search-button').disabled = false;
  notice('Connected. Published age bands give an exact count of the aligned census cohort.', 'success');
  await search();
}
function closeAuthorization() { $('auth-dialog').close(); state.connection = null; $('auth-frame').src = 'about:blank'; }
$('authorize').addEventListener('click', () => {
  state.connection = [...crypto.getRandomValues(new Uint8Array(16))].map(value => value.toString(16).padStart(2, '0')).join('');
  $('auth-frame').src = `/docs/?frontend_connect=${state.connection}`; $('auth-dialog').showModal();
});
window.addEventListener('message', async event => {
  const payload = event.data;
  if (event.origin !== location.origin || event.source !== $('auth-frame').contentWindow || !state.connection ||
      payload?.type !== 'demographics:authorized' || payload.connection !== state.connection ||
      typeof payload.accessToken !== 'string' || payload.accessToken.length < 20 || payload.accessToken.length > 256) return;
  state.token = payload.accessToken; state.expires = Date.now() + Math.min(Number(payload.expiresIn) || 3600, 86400) * 1000; state.session++;
  closeAuthorization(); $('connection-status').textContent = 'API connected'; $('connection-status').className = 'connection-state connected';
  $('authorize').hidden = true; $('disconnect').hidden = false;
  try { await loadWorkspace(); } catch (error) { notice(error.message, 'error'); }
});
function formQuery() {
  return {integration_id: $('integration').value, source_year: state.options?.source_years[0] || 2022, target_year: $('target-year').value,
    age_min: $('age-min').value, age_max: $('age-max').value, level: $('level').value, state_code: $('state').value,
    city_code: $('city').disabled ? '' : $('city').value, sort: $('sort').value, estimate: $('estimate').checked ? 'true' : 'false'};
}
async function search(page = 1, saved = false) {
  if (state.busy || !$('search-form').reportValidity()) return;
  if (Number($('age-max').value) < Number($('age-min').value)) { notice('The maximum age must be greater than or equal to the minimum age.', 'error'); return; }
  state.busy = true; $('search-button').disabled = true; $('search-button').textContent = 'Exploring…';
  try {
    const query = saved && state.query ? state.query : formQuery();
    const body = await api('/api/v1/demographics/search/', {...query, page, page_size: 15});
    state.query = query; state.result = body; renderResults(body);
    if (!body.count) notice(body.empty_reason || 'No imported data matches this search.');
    else if (body.summary.incomplete_locations) notice('This range is not fully covered by the census. Births after the source year and missing age bands cannot be inferred.');
    else if (body.summary.bounded_locations && query.estimate !== 'true') notice('This range intersects partial age bands. The table shows bounds; overlapping bounds do not establish a definite ranking.');
    else if (query.estimate === 'true' && body.summary.bounded_locations) notice('Proportional estimates assume an even distribution within each closed age band. They are not official population forecasts.');
    else notice(`Showing the observed ${query.source_year} cohort aligned by ${body.years_advanced} years. Births, deaths and migration are not modeled.`, 'success');
  } catch (error) { notice(error.message, 'error'); }
  finally { state.busy = false; $('search-button').disabled = !state.token || !state.options?.integrations?.length; $('search-button').textContent = 'Explore locations →'; }
}
function countText(row, estimate) {
  if (row.exact_count !== null) return format(row.exact_count);
  if (estimate && row.estimated_count !== null) return `≈ ${format(row.estimated_count)}`;
  return row.upper_bound === null ? 'Not fully covered' : `${format(row.lower_bound)}–${format(row.upper_bound)}`;
}
function shareText(row) {
  if (row.lower_share_percent === null) return '—';
  if (row.upper_share_percent === null) return `≥ ${format(row.lower_share_percent)}%`;
  return row.lower_share_percent === row.upper_share_percent ? `${format(row.lower_share_percent)}%` : `${format(row.lower_share_percent)}–${format(row.upper_share_percent)}%`;
}
function badge(row, estimate) {
  if (row.match === 'incomplete_coverage') return el('span', 'Incomplete', 'pill incomplete');
  if (row.match === 'exact_band_match') return el('span', 'Exact band match', 'pill');
  return el('span', estimate && row.estimated_count !== null ? 'Proportional estimate' : 'Bounded count', 'pill bounded');
}
function renderResults(body) {
  const q = body.query; syncYears();
  $('metric-locations').textContent = format(body.count);
  $('metric-coverage').textContent = body.count ? `${body.summary.exact_locations}/${body.count}` : '—';
  $('metric-coverage-help').textContent = 'Locations with an exact band match';
  $('results-title').textContent = `${levels[q.level]} · ages ${q.age_min}–${q.age_max}`;
  const rankLabel = {lower_bound: 'confirmed lower bound', upper_bound: 'possible upper bound', estimate: 'proportional estimate', share: 'confirmed source share'}[q.sort];
  $('results-subtitle').textContent = `${q.source_year} census cohort → ${q.target_year} age alignment · ranked by ${rankLabel}`;
  $('empty-state').hidden = !!body.count;
  if (!body.count) $('empty-state').replaceChildren(el('span', '◎', 'empty-mark'), el('h3', 'No data for this geography'), el('p', body.empty_reason), el('span', 'A missing source is not a zero population', 'quiet-tag'));
  $('table-wrap').hidden = $('pagination').hidden = !body.count; $('export').disabled = !body.count;
  $('results-body').replaceChildren();
  const maximum = Math.max(1, ...body.results.map(row => row[body.rank_basis] || 0));
  for (const row of body.results) {
    const tr = el('tr'), place = el('td'), count = el('td', undefined, 'count-cell'), share = el('td'), match = el('td'), details = el('td');
    tr.append(el('td', row.rank === null ? '—' : String(row.rank).padStart(2, '0')));
    place.append(el('strong', row.geography.name), el('small', `${row.geography.parent_name || 'Brazil'} · ${row.geography.code}`));
    const bar = el('progress', undefined, 'mini-progress'); bar.max = maximum; bar.value = row[body.rank_basis] || 0; bar.setAttribute('aria-label', 'Relative value for selected ranking basis');
    count.append(el('span', countText(row, q.estimate)), bar); share.append(el('span', shareText(row)), el('small', 'of source age total')); match.append(badge(row, q.estimate));
    const button = el('button', '↗', 'row-detail'); button.type = 'button'; button.setAttribute('aria-label', `View calculation for ${row.geography.name}`); button.addEventListener('click', () => showDetails(row, body)); details.append(button);
    tr.append(place, count, share, match, details); $('results-body').append(tr);
  }
  $('page-summary').textContent = `${(body.page - 1) * body.page_size + 1}–${Math.min(body.page * body.page_size, body.count)} of ${format(body.count)} locations`;
  $('previous').disabled = body.page <= 1; $('next').disabled = body.page * body.page_size >= body.count;
}
async function showDetails(row, body) {
  $('detail-title').textContent = row.geography.name;
  const content = $('detail-content'), metrics = el('div', undefined, 'detail-metrics');
  content.replaceChildren(el('p', `${body.query.source_year} observed cohort aligned to ${body.query.target_year}. Bounds describe intersections of published age bands, not uncertainty from deaths or migration.`));
  for (const [label, value] of [['Confirmed lower bound', row.lower_bound], ['Possible upper bound', row.upper_bound], ['Proportional estimate', row.estimated_count]]) {
    const item = el('div', label); item.append(el('strong', value === null ? 'Unavailable' : format(value))); metrics.append(item);
  }
  content.append(metrics);
  const messages = {post_census_births: 'This range includes births after the source census.', missing_or_suppressed_band: 'A required age band is missing or suppressed.', open_ended_band_estimate_unavailable: 'The open-ended age band cannot be proportionally divided.'};
  for (const flag of row.flags) content.append(el('p', messages[flag] || flag));
  const table = el('table'), head = el('tr');
  for (const title of ['Source ages', 'Aligned ages', 'Published people', 'Intersection']) head.append(el('th', title));
  table.append(head);
  for (const band of row.bands) {
    const tr = el('tr');
    for (const text of [band.source_age_max === null ? `${band.source_age_min}+` : `${band.source_age_min}–${band.source_age_max}`, band.aligned_age_max === null ? `${band.aligned_age_min}+` : `${band.aligned_age_min}–${band.aligned_age_max}`, band.count === null ? 'Missing / suppressed' : format(band.count), band.fully_included ? 'Entire band' : 'Partial band']) tr.append(el('td', text));
    table.append(tr);
  }
  content.append(table, el('h3', 'Source lineage'));
  const lineage = el('p', 'Loading the latest source observation…'); content.append(lineage); $('detail-dialog').showModal();
  const first = row.bands.find(band => band.statistic_id);
  if (!first) { lineage.textContent = 'This age range has no matching source band.'; return; }
  try {
    const data = await api(`/api/v1/demographics/${first.statistic_id}/observations/`, {page_size: 1}), source = data.results[0];
    if (!$('detail-dialog').open || $('detail-title').textContent !== row.geography.name) return;
    lineage.textContent = source ? `Reference ${source.reference_period} · ${source.transformation_version} · original columns ${source.source_columns} · collected ${new Date(source.collected_at).toLocaleString('en-GB')}. Source: ${source.source_url}. SHA-256: ${source.source_sha256}` : 'No source observation is available.';
  } catch (error) { lineage.textContent = error.message; }
}
async function showCoverage() {
  $('coverage-panel').hidden = false; $('coverage-content').replaceChildren(el('p', 'Loading source coverage…')); $('coverage-panel').scrollIntoView({behavior: 'smooth', block: 'start'});
  if (!state.token) { $('coverage-content').replaceChildren(el('p', 'Authorize the API to inspect the imported source coverage.')); return; }
  try {
    const rows = await allPages('/api/v1/ibge/coverage/', {integration_id: $('integration').value, latest: 'true'}, 3000), container = $('coverage-content');
    container.replaceChildren(el('p', 'Census 2022 reference. Age alignment does not update the census measurements. Income in the underlying API retains its original 2022 definition and unit.', 'coverage-summary'));
    const groups = new Map();
    for (const row of rows) { const key = `${row.level}:${row.status}`; if (!groups.has(key)) groups.set(key, {row, count: 0}); groups.get(key).count++; }
    for (const {row, count} of groups.values()) {
      const item = el('div', undefined, 'coverage-item'), title = el('strong', `${levels[row.level] || row.level} · ${row.status.replaceAll('_', ' ')}`);
      title.append(el('span', `${count} coverage record${count === 1 ? '' : 's'}`, 'pill')); item.append(title, el('p', row.message)); container.append(item);
    }
    if (!rows.length) container.append(el('p', 'No coverage evidence has been imported for this source.'));
  } catch (error) { $('coverage-content').replaceChildren(el('p', error.message)); }
}
function csvField(value) {
  let text = value === null || value === undefined ? '' : String(value);
  if (/^[=+\-@\t\r]/.test(text)) text = `'${text}`;
  return `"${text.replaceAll('"', '""')}"`;
}
async function exportCsv() {
  if (!state.result) return;
  $('export').disabled = true;
  try {
    const q = {...state.query}, method = state.result.method;
    const rows = await allPages('/api/v1/demographics/search/', q, 5000);
    const columns = ['rank', 'location', 'geography_code', 'level', 'source_year', 'analysis_year', 'years_advanced', 'age_min', 'age_max', 'lower_bound', 'upper_bound', 'estimated_count', 'source_age_total', 'match', 'flags', 'method'];
    const lines = [columns.map(csvField).join(',')];
    for (const row of rows) lines.push([row.rank, row.geography.name, row.geography.code, row.geography.level, q.source_year, q.target_year, Number(q.target_year)-Number(q.source_year), q.age_min, q.age_max, row.lower_bound, row.upper_bound, row.estimated_count, row.source_age_total, row.match, row.flags.join(';'), method].map(csvField).join(','));
    const url = URL.createObjectURL(new Blob(['\ufeff' + lines.join('\r\n')], {type: 'text/csv;charset=utf-8'})), link = el('a');
    link.href = url; link.download = `census-cohorts-${q.target_year}-ages-${q.age_min}-${q.age_max}.csv`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) { notice(error.message, 'error'); } finally { $('export').disabled = !state.result?.count; }
}
$('close-auth').addEventListener('click', closeAuthorization); $('auth-dialog').addEventListener('cancel', closeAuthorization);
$('disconnect').addEventListener('click', () => disconnect()); $('close-detail').addEventListener('click', () => $('detail-dialog').close());
$('search-form').addEventListener('submit', event => { event.preventDefault(); search(); });
$('previous').addEventListener('click', () => search(state.result.page - 1, true)); $('next').addEventListener('click', () => search(state.result.page + 1, true));
$('export').addEventListener('click', exportCsv); $('coverage-nav').addEventListener('click', showCoverage);
$('explorer-nav').addEventListener('click', () => $('search-form').scrollIntoView({behavior: 'smooth', block: 'start'}));
$('state').addEventListener('change', updateCities); $('level').addEventListener('change', updateCities);
$('city').addEventListener('change', () => { if ($('city').value) $('state').value = $('city').value.slice(0, 2); });
$('target-year').addEventListener('input', () => { syncYears(); presets(); });
$('age-preset').addEventListener('change', () => { if ($('age-preset').value) [$('age-min').value, $('age-max').value] = $('age-preset').value.split(':'); });
for (const id of ['age-min', 'age-max']) $(id).addEventListener('input', () => { $('age-preset').value = ''; });
$('estimate').addEventListener('change', () => {
  $('sort').querySelector('option[value="estimate"]').disabled = !$('estimate').checked;
  if ($('estimate').checked) $('sort').value = 'estimate'; else if ($('sort').value === 'estimate') $('sort').value = 'lower_bound';
});
$('integration').addEventListener('change', async () => { try { resetResults(); $('coverage-panel').hidden = true; $('coverage-content').replaceChildren(); $('state').value = ''; $('city').value = ''; await loadGeographies(); notice('Source changed. Apply the search to explore this integration.'); } catch (error) { notice(error.message, 'error'); } });
$('reset').addEventListener('click', () => {
  $('target-year').value = state.options?.current_year || yearNow;
  const delta = Number($('target-year').value) - (state.options?.source_years[0] || 2022);
  $('age-min').value = delta; $('age-max').value = delta + 4; $('level').value = 'district'; $('estimate').checked = false; $('sort').value = 'lower_bound';
  const imported = state.options?.integrations.find(row => row.id === $('integration').value)?.levels || [];
  if (imported.length && !imported.includes('district')) $('level').value = imported.includes('city') ? 'city' : imported[0];
  $('sort').querySelector('option[value="estimate"]').disabled = true; syncYears(); presets(); updateCities();
});
$('target-year').max = $('target-year').value = yearNow; $('age-min').value = yearNow - 2022; $('age-max').value = yearNow - 2022 + 4; syncYears(); presets();
setInterval(() => { if (state.token && Date.now() >= state.expires) disconnect('Your API session expired. Authorize again through Swagger.'); }, 15000);
