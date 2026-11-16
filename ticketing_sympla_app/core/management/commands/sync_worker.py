import time
import signal
from pathlib import Path
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from core.services import enqueue_due, process_one


class Command(BaseCommand):
    help = 'Persistent schedule/queue worker; supervise as a service. --once processes one tick.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true')
        parser.add_argument('--provider', choices=['sympla', 'ibge'], default='sympla')

    def handle(self, *args, **options):
        self.stopping = False
        def stop(signum, frame):
            self.stopping = True
        previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
        self.stdout.write('Scheduler worker started. Checking daily schedules every five seconds between imports.')
        self.stdout.write('Every import uses its registered integration connector, API account credentials and current synchronization:write permission.')
        try:
            while not self.stopping:
                Path('/tmp/worker-heartbeat').touch() if Path('/tmp').is_dir() else None
                close_old_connections()
                due = enqueue_due(provider=options['provider'])
                if due:
                    self.stdout.write(f'Scheduled synchronizations queued: {due}')
                run = process_one(provider=options['provider'])
                if run:
                    self.stdout.write(f'run_id={run.pk} owner={run.owner.identifier} integration_id={run.integration_id} source={run.source} status={run.status} '
                                      f'counts={run.counts} error_code={run.error_code or "none"}')
                if options['once']:
                    return
                time.sleep(5)
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            self.stdout.write('Scheduler worker stopped after completing its current import.')
