from django.core.management.base import BaseCommand
from django.db import transaction
from core.map_reference import populate
from core.services import audit
from core.models import Coordinator


class Command(BaseCommand):
    help = 'Populate official map coordinates and territorial areas for imported geographies.'

    @transaction.atomic
    def handle(self, *args, **options):
        Coordinator.objects.select_for_update().get(pk=1)
        count = populate()
        audit('map-reference-setup', 'geography.map_reference_loaded', 'geography', '2022', {'locations': count})
        self.stdout.write(f'Official map references ready: {count}.')
