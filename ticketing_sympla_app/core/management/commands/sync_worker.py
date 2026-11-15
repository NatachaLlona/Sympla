import time
import signal
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
        self.stopping = False
        def stop(signum, frame):
            self.stopping = True
        previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
        self.stdout.write('Scheduler worker started. Checking daily schedules every five seconds between imports.')
        self.stdout.write('Every import uses its API owner\'s Sympla token and current write permission.')
        try:
            while not self.stopping:
                close_old_connections()
                due = enqueue_due()
                if due:
                    self.stdout.write(f'Scheduled synchronizations queued: {due}')
                run = process_one()
                if run:
                    self.stdout.write(f'run_id={run.pk} owner={run.owner.identifier} source={run.source} status={run.status} '
                                      f'counts={run.counts} error_code={run.error_code or "none"}')
                if options['once']:
                    return
                time.sleep(5)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            self.stdout.write('Scheduler worker stopped after completing its current import.')
