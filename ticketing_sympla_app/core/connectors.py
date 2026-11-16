"""Explicit connector registry. API input cannot select arbitrary code or URLs."""
from typing import Protocol
from .sync_exception import SyncError
from .integration_modules.sympla.connector import SymplaConnector
from .integration_modules.ibge.connector import IbgeConnector


class IntegrationConnector(Protocol):
    code: str
    version: str
    credential_scope: str
    domain: str
    running_slot: int

    def configuration_error(self, integration, api_account) -> str | None: ...
    def collect(self, integration, api_account) -> list[dict] | dict: ...
    def validate_configuration(self, configuration: dict) -> dict: ...


CONNECTORS: dict[str, IntegrationConnector] = {'sympla': SymplaConnector(), 'ibge': IbgeConnector()}


def connector_for(code):
    try:
        return CONNECTORS[code]
    except KeyError:
        raise SyncError('unsupported_integration') from None
