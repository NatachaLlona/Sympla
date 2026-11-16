from dataclasses import dataclass
from ...sympla import fetch_events, configuration_error
from ...provider_secrets import decrypt_token

@dataclass(frozen=True)
class SymplaConnector:
    code: str = 'sympla'
    version: str = 'sympla.events.v1'
    credential_scope: str = 'api_account'
    domain: str = 'events'
    running_slot: int = 1

    def validate_configuration(self, configuration):
        if configuration:
            raise ValueError('Sympla integration configuration must be empty.')
        return {}

    def configuration_error(self, integration, api_account):
        return configuration_error(decrypt_token(api_account))

    def collect(self, integration, api_account):
        return fetch_events(token=decrypt_token(api_account))

    def normalize(self, payload):
        from ...event_mapping import normalize
        return normalize(payload)


