import time
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from core.services import enqueue_due, process_one
from core.sympla import configuration_error
from core.sync_errors import message


class Command(BaseCommand):
    help = 'Persistent schedule/queue worker; supervise as a service. --once processes one tick.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true')

    def handle(self, *args, **options):
        self.stdout.write('Scheduler worker started. Checking daily schedules every five seconds between imports.')
        if configuration_error():
            self.stderr.write('Configuration warning: ' + message('upstream_configuration'))
        while True:
            close_old_connections()
            due = enqueue_due()
            if due:
                self.stdout.write(f'Scheduled synchronizations queued: {due}')
            run = process_one()
            if run:
                self.stdout.write(f'run_id={run.pk} source={run.source} status={run.status} '
                                  f'counts={run.counts} error_code={run.error_code or "none"}')
            if options['once']:
                return
            time.sleep(5)
