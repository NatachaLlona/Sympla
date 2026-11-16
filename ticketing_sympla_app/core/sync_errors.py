MESSAGES = {
    'unsupported_integration': 'No connector is registered for this integration provider.',
    'integration_unavailable': 'The integration is inactive or deleted.',
    'integration_changed': 'The integration changed during the import. No event changes were committed.',
    'owner_authorization_changed': 'The owner permission or Sympla token changed during the import. No event changes were committed.',
    'owner_not_authorized': 'The owner is inactive or no longer has write permission.',
    'provider_secret_unavailable': 'The provider token cannot be decrypted. Check the provider encryption key.',
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
