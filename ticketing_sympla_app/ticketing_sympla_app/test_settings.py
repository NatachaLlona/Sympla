from .settings import *

# Test databases are created/destroyed by Django; never use a real upstream token.
DEBUG = True
SECURE_SSL_REDIRECT = False
SYMPLA_API_KEY = ''
PROVIDER_ENCRYPTION_KEY = 'MDEyMzQ1Njc4OTAxMjM0NTY3ODkwMTIzNDU2Nzg5MDE='
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
if os.getenv('TEST_POSTGRES_HOST'):
    DATABASES = {'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'sympla_qa', 'USER': 'sympla_qa',
        'PASSWORD': 'disposable-local-qa-only',
        'HOST': os.environ['TEST_POSTGRES_HOST'],
        'PORT': os.getenv('TEST_POSTGRES_PORT', '55439'),
    }}
