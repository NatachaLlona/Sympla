"""Create the national IBGE capital scope and queue an owned, audited import."""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from core.models import ApiUser, Coordinator, Integration, SyncRun
from core.integration_modules.ibge.connector import configuration
from core.integration_modules.ibge.metropolitan import PRESET, municipality_codes
from core.rbac import permitted
from core.services import audit, enqueue


class Command(BaseCommand):
    help = 'Create the capital/metropolitan IBGE integration and queue its initial import.'

    def add_arguments(self, parser):
        parser.add_argument('--client-id', required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        Coordinator.objects.select_for_update().get(pk=1)
        api_account = ApiUser.objects.select_for_update().filter(client_id=options['client_id'], is_active=True, deleted_at__isnull=True).first()
        if not api_account or not all(permitted(api_account, permission) for permission in ('integrations:write', 'synchronization:write')):
            raise CommandError('Choose an active API account with integrations:write and synchronization:write permissions.')
        scope = configuration({'geographic_preset': PRESET, 'levels': ['city']})
        matches = Integration.objects.filter(owner=api_account, provider='ibge', deleted_at__isnull=True,
            configuration__geographic_preset=PRESET)
        if matches.count() > 1:
            raise CommandError('Multiple matching integrations exist. Select an integration through the API instead.')
        integration = matches.first()
        if not integration:
            if Integration.objects.filter(owner=api_account, deleted_at__isnull=True).count() >= 100:
                raise CommandError('The API account already has 100 integrations.')
            integration = Integration.objects.create(owner=api_account, name='IBGE - Capitals and metropolitan areas', provider='ibge', configuration=scope)
            audit(api_account.client_id, 'integration.created', 'integration', integration.pk,
                {'provider': 'ibge', 'configuration': scope}, owner=api_account)
        if not integration.active or integration.configuration != scope:
            raise CommandError('The existing preset integration was changed or deactivated. Review it through the API.')
        pending = SyncRun.objects.filter(integration=integration, status__in=['queued', 'running']).first()
        run = pending or enqueue(api_account.client_id, owner=api_account, integration=integration)
        self.stdout.write(f'Integration: {integration.pk}; municipalities: {len(municipality_codes())}; run: {run.pk}; status: {run.status}')
