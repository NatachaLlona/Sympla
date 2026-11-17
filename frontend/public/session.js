// The existing Swagger dialog remains the only interactive API credential form.
export function apiSession(onConnect, onDisconnect) {
  const $ = id => document.getElementById(id);
  let token = null, expires = 0, connection = null, generation = 0;
  function close() { $('auth-dialog').close(); connection = null; $('auth-frame').src = 'about:blank'; }
  function disconnect() {
    token = null; expires = 0; generation++;
    $('authorize').hidden = false; $('disconnect').hidden = true;
    $('connection-status').textContent = 'Not connected';
    onDisconnect();
  }
  $('authorize').addEventListener('click', () => {
    connection = [...crypto.getRandomValues(new Uint8Array(16))].map(value => value.toString(16).padStart(2, '0')).join('');
    $('auth-frame').src = `/docs/?frontend_connect=${connection}`; $('auth-dialog').showModal();
  });
  $('close-auth').addEventListener('click', close); $('auth-dialog').addEventListener('cancel', close);
  $('disconnect').addEventListener('click', disconnect);
  window.addEventListener('message', async event => {
    const body = event.data;
    if (event.origin !== location.origin || event.source !== $('auth-frame').contentWindow || !connection ||
        body?.type !== 'demographics:authorized' || body.connection !== connection ||
        typeof body.accessToken !== 'string' || body.accessToken.length < 20 || body.accessToken.length > 256) return;
    token = body.accessToken; expires = Date.now()+Math.min(Number(body.expiresIn)||3600, 86400)*1000; generation++;
    close(); $('authorize').hidden = true; $('disconnect').hidden = false; $('connection-status').textContent = 'API connected';
    try { await onConnect(); } catch (error) { document.getElementById('notice').textContent = error.message; }
  });
  setInterval(() => { if (token && Date.now() >= expires) disconnect(); }, 15000);
  async function get(path, parameters = {}) {
    if (!token || Date.now() >= expires) { disconnect(); throw new Error('Authorize through Swagger to search.'); }
    const url = new URL(path, location.origin), current = generation;
    for (const [key, value] of Object.entries(parameters)) if (value !== '' && value !== null && value !== undefined) url.searchParams.set(key, value);
    const response = await fetch(url, {headers: {Authorization: `Bearer ${token}`}, credentials: 'omit', cache: 'no-store'});
    if (current !== generation) throw new Error('The API session changed.');
    if (response.status === 401) { disconnect(); throw new Error('The API session expired. Authorize again.'); }
    const body = await response.json();
    if (!response.ok) throw new Error(body.message || (response.status === 403 ? `This API account needs ${body.required_permission || 'read'} permission.` : body.error || 'API request failed.'));
    return body;
  }
  async function pages(path, params = {}) {
    const result = [];
    for (let page = 1; page <= 100; page++) {
      const body = await get(path, {...params, page, page_size: 100}); result.push(...body.results);
      if (result.length >= body.count) return result;
    }
    throw new Error('Narrow the selected source.');
  }
  return {get, pages};
}
