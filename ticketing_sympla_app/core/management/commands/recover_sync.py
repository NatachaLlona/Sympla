from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from core.models import SyncRun
from core.services import audit


class Command(BaseCommand):
    help = 'Mark an abandoned run failed. Stop and verify all workers before using this command.'

    def add_arguments(self, parser):
        parser.add_argument('run_id')
        parser.add_argument('--workers-stopped', action='store_true', required=True)

    @transaction.atomic
    def handle(self, *args, **options):
        run = SyncRun.objects.select_for_update().filter(pk=options['run_id'], status='running').first()
        if not run:
            raise CommandError('Running job not found')
        run.status, run.running_slot, run.finished_at = 'failed', None, timezone.now()
        run.error_code = 'worker_interrupted'
        run.save()
        audit('local-administrator', 'sync.recovered', 'sync_run', run.pk, interaction=run.pk, owner=run.owner)
