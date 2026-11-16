class SyncError(Exception):
    def __init__(self, code, *, http_status=None, page=None):
        super().__init__(code)
        self.details = {}
        if http_status is not None:
            self.details["upstream_http_status"] = http_status
        if page is not None:
            self.details["page"] = page
