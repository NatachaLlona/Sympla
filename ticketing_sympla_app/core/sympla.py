import json
import time
from urllib.parse import urlsplit
import requests
from django.conf import settings


class SyncError(Exception):
    pass


def fetch_events():
    """Bounded HTTPS fetch; never log credentials or upstream error bodies."""
    base = settings.SYMPLA_API_HOST.rstrip('/')
    parsed = urlsplit(base)
    if (parsed.scheme != 'https' or parsed.hostname != 'api.sympla.com.br'
            or parsed.port not in (None, 443) or parsed.username or parsed.password
            or parsed.query or parsed.fragment or not settings.SYMPLA_API_KEY):
        raise SyncError('upstream_configuration')
    deadline = time.monotonic() + settings.SYNC_TIMEOUT_SECONDS
    events, seen, cursors = [], set(), set()
    total_bytes = 0
    cursor = None
    with requests.Session() as session:
        session.trust_env = False
        for page in range(1, settings.SYNC_MAX_PAGES + 1):
            params = {'page_size': 200}
            params.update({'cursor': cursor} if cursor else {'page': page})
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SyncError('upstream_deadline')
            try:
                with session.get(base + '/events', headers={'s_token': settings.SYMPLA_API_KEY},
                                 params=params, timeout=(min(5, remaining), min(10, remaining)),
                                 allow_redirects=False, stream=True) as response:
                    if response.status_code != 200:
                        raise SyncError('upstream_http_error')
                    chunks, size = [], 0
                    for chunk in response.iter_content(8192):
                        size += len(chunk)
                        total_bytes += len(chunk)
                        if (size > settings.SYNC_MAX_PAGE_BYTES or total_bytes > settings.SYNC_MAX_TOTAL_BYTES
                                or time.monotonic() > deadline):
                            raise SyncError('upstream_limit')
                        chunks.append(chunk)
                    data = json.loads(b''.join(chunks))
            except (requests.RequestException, ValueError) as exc:
                raise SyncError('upstream_invalid_response') from exc
            if not isinstance(data, dict) or not isinstance(data.get('data'), list):
                raise SyncError('upstream_invalid_response')
            batch = data['data']
            for event in batch:
                external_id = event.get('id') if isinstance(event, dict) else None
                if (isinstance(external_id, bool) or not isinstance(external_id, (int, str))
                        or not str(external_id) or len(str(external_id)) > 200):
                    raise SyncError('upstream_invalid_event')
                if str(external_id) in seen:
                    raise SyncError('upstream_duplicate_event')
                seen.add(str(external_id))
                events.append(event)
                if len(events) > settings.SYNC_MAX_EVENTS:
                    raise SyncError('upstream_limit')
            pagination = data.get('pagination')
            if not isinstance(pagination, dict):
                raise SyncError('upstream_invalid_pagination')
            next_cursor = pagination.get('next_cursor')
            if next_cursor:
                if not isinstance(next_cursor, str) or len(next_cursor) > 2048 or next_cursor in cursors or not batch:
                    raise SyncError('upstream_invalid_pagination')
                cursors.add(next_cursor)
                cursor = next_cursor
                continue
            if cursor or 'next_cursor' in pagination:
                return events
            has_next = pagination.get('has_next')
            if not isinstance(has_next, bool):
                raise SyncError('upstream_invalid_pagination')
            if not has_next:
                return events
            if not batch:
                raise SyncError('upstream_invalid_pagination')
    raise SyncError('upstream_page_limit')
