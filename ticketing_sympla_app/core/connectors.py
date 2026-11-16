"""Explicit connector registry. API input cannot select arbitrary code or URLs."""
from dataclasses import dataclass
from typing import Protocol
from .sympla import fetch_events, configuration_error, SyncError
from .provider_secrets import decrypt_token


class EventConnector(Protocol):
    code: str
    version: str
    credential_scope: str

    def configuration_error(self, integration, api_account) -> str | None: ...
    def collect(self, integration, api_account) -> list[dict]: ...
    def normalize(self, payload: dict) -> dict: ...


@dataclass(frozen=True)
class SymplaConnector:
    code: str = 'sympla'
    version: str = 'sympla.events.v1'
    credential_scope: str = 'api_account'

    def configuration_error(self, integration, api_account):
        return configuration_error(decrypt_token(api_account))

    def collect(self, integration, api_account):
        return fetch_events(token=decrypt_token(api_account))

    def normalize(self, payload):
        from .event_mapping import normalize
        return normalize(payload)


CONNECTORS: dict[str, EventConnector] = {'sympla': SymplaConnector()}


def connector_for(code):
    try:
        return CONNECTORS[code]
    except KeyError:
        raise SyncError('unsupported_integration') from None
