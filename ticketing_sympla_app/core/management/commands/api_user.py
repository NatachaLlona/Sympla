import hashlib
import re
import secrets
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from core.models import ApiUser
from core.services import audit


class Command(BaseCommand):
    help = 'Create, rotate or revoke an API user. A new token is displayed once; store it securely.'

    def add_arguments(self, parser):
        parser.add_argument('action', choices=['create', 'rotate', 'revoke'])
        parser.add_argument('username')
        parser.add_argument('--write', action='store_true', help='Allow scheduling and manual synchronization')

    @transaction.atomic
    def handle(self, *args, **options):
        name, action = options['username'], options['action']
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', name):
            raise CommandError('Invalid username')
        user = ApiUser.objects.select_for_update().filter(username=name).first()
        if action == 'create' and user:
            raise CommandError('User already exists; rotate instead')
        if action != 'create' and not user:
            raise CommandError('User not found')
        token = None
        if action == 'revoke':
            user.is_active = False
            user.save(update_fields=['is_active'])
        else:
            token = secrets.token_urlsafe(48)
            digest = hashlib.sha256(token.encode()).hexdigest()
            if user:
                user.token_hash, user.is_active = digest, True
                user.save(update_fields=['token_hash', 'is_active'])
            else:
                user = ApiUser.objects.create(username=name, token_hash=digest, can_write=options['write'])
        audit('local-administrator', 'api_user.' + action, 'api_user', user.pk,
              {'username': name, 'active': user.is_active, 'can_write': user.can_write})
        if token:
            self.stdout.write(token)
        else:
            self.stdout.write('User revoked')
