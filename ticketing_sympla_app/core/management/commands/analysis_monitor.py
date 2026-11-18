"""Emit local alerts when a watched scenario's owned data changes; no external messaging."""
import signal
import time
from pathlib import Path
from django.core.management.base import BaseCommand
from django.db import close_old_connections, transaction
from core.models import AnalysisScenario, AnalysisAlert, ScenarioSnapshot, Coordinator
from core.analysis_views import signature
from core.rbac import permitted


def check_updates():
    count = 0
    signatures = {}
    with transaction.atomic():
        Coordinator.objects.select_for_update().get(pk=1)
        for scenario in AnalysisScenario.objects.filter(watch=True, deleted_at__isnull=True).select_related('owner'):
            if not all(permitted(scenario.owner, permission) for permission in ['scenarios:read', 'demographics:read']):
                continue
            if scenario.filters.get('event_id') and not permitted(scenario.owner, 'events:read'):
                continue
            latest = ScenarioSnapshot.objects.filter(scenario=scenario).order_by('-pk').first()
            if scenario.owner_id not in signatures:
                signatures[scenario.owner_id] = signature(scenario.owner)
            stamp = signatures[scenario.owner_id]
            if latest and latest.source_signature != stamp:
                _, created = AnalysisAlert.objects.get_or_create(scenario=scenario, source_signature=stamp,
                    defaults={'message': 'Owned source data changed after this scenario was captured. Capture a new snapshot to compare.'})
                count += created
    return count


class Command(BaseCommand):
    help = 'Monitor watched scenarios and create local source-update alerts.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true')

    def handle(self, *args, **options):
        running = True
        def stop(*_):
            nonlocal running
            running = False
        signal.signal(signal.SIGTERM, stop)
        while running:
            Path('/tmp/analysis-heartbeat').touch()
            close_old_connections()
            count = check_updates()
            if count:
                self.stdout.write(f'Local analysis alerts created: {count}')
            if options['once']:
                return
            for _ in range(30):
                if not running:
                    break
                time.sleep(1)
