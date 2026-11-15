import json
import time
from urllib.parse import urlsplit
import requests
from django.conf import settings


class SyncError(Exception):
    def __init__(self, code, *, http_status=None, page=None):
        super().__init__(code)
        self.details = {}
        if http_status is not None:
            self.details['upstream_http_status'] = http_status
        if page is not None:
            self.details['page'] = page


def configuration_error():
    base = settings.SYMPLA_API_HOST.rstrip('/')
    try:
        parsed = urlsplit(base)
        invalid = (parsed.scheme != 'https' or parsed.hostname != 'api.sympla.com.br'
                   or parsed.port not in (None, 443) or parsed.username or parsed.password
                   or parsed.query or parsed.fragment or not settings.SYMPLA_API_KEY)
    except ValueError:
        invalid = True
    return 'upstream_configuration' if invalid else None


def fetch_events():
    """Bounded HTTPS fetch; never log credentials or upstream error bodies."""
    if configuration_error():
        raise SyncError('upstream_configuration')
    base = settings.SYMPLA_API_HOST.rstrip('/')
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
                        raise SyncError('upstream_http_error', http_status=response.status_code, page=page)
                    chunks, size = [], 0
                    for chunk in response.iter_content(8192):
                        size += len(chunk)
                        total_bytes += len(chunk)
                        if (size > settings.SYNC_MAX_PAGE_BYTES or total_bytes > settings.SYNC_MAX_TOTAL_BYTES
                                or time.monotonic() > deadline):
                            raise SyncError('upstream_limit')
                        chunks.append(chunk)
                    data = json.loads(b''.join(chunks))
            except requests.Timeout as exc:
                raise SyncError('upstream_timeout', page=page) from exc
            except requests.ConnectionError as exc:
                raise SyncError('upstream_connection_error', page=page) from exc
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
            if 'has_next' not in pagination:
                # Sympla's cursor contract omits next_cursor on the terminal page,
                # including a single-page result. quantity is the current batch count.
                quantity, size = pagination.get('quantity'), pagination.get('page_size')
                if (type(quantity) is int and quantity == len(batch) and type(size) is int
                        and size > 0 and len(batch) <= size):
                    return events
                raise SyncError('upstream_invalid_pagination')
            if not isinstance(has_next, bool):
                raise SyncError('upstream_invalid_pagination')
            if not has_next:
                return events
            if not batch:
                raise SyncError('upstream_invalid_pagination')
    raise SyncError('upstream_page_limit')
