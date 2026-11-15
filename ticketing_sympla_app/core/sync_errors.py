MESSAGES = {
    'upstream_configuration': 'Sympla API credentials or host are not configured. Run python start.py --configure-sympla.',
    'upstream_http_error': 'Sympla returned an unsuccessful HTTP response. Check the upstream status and account permissions.',
    'upstream_timeout': 'The connection to Sympla timed out.',
    'upstream_connection_error': 'Could not connect to Sympla. Check network and DNS availability.',
    'upstream_invalid_response': 'Sympla returned an invalid response.',
    'upstream_invalid_event': 'A Sympla event has an invalid structure.',
    'upstream_invalid_pagination': 'Sympla returned invalid pagination metadata.',
    'upstream_duplicate_event': 'Sympla returned a duplicate event across pages.',
    'upstream_limit': 'The synchronization exceeded its size or time limit.',
    'upstream_deadline': 'The synchronization exceeded its elapsed-time budget.',
    'upstream_page_limit': 'The synchronization exceeded the maximum number of pages.',
    'sync_internal_error': 'An internal import error occurred; event changes were rolled back.',
    'worker_interrupted': 'A worker was interrupted before completing this synchronization.',
}


def message(code):
    return MESSAGES.get(code, 'Synchronization failed. Check the server logs using the run ID.')
