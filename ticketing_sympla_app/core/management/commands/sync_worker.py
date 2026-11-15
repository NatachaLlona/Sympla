import time
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from core.services import enqueue_due, process_one


class Command(BaseCommand):
    help = 'Persistent schedule/queue worker; supervise as a service. --once processes one tick.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true')

    def handle(self, *args, **options):
        while True:
            close_old_connections()
            enqueue_due()
            run = process_one()
            if run:
                self.stdout.write(f'{run.pk}: {run.status}')
            if options['once']:
                return
            time.sleep(5)
