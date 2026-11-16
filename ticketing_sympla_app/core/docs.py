import secrets
from importlib.resources import files
from django.conf import settings
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET
from .openapi import SCHEMA


def enabled():
    if not settings.DOCS_ENABLED:
        raise Http404


@require_GET
def schema(request):
    enabled()
    response = JsonResponse(SCHEMA)
    response['Cache-Control'] = 'no-store'
    return response


@require_GET
def swagger(request):
    enabled()
    nonce = secrets.token_urlsafe(24)
    response = render(request, 'core/swagger.html', {'nonce': nonce})
    response['Cache-Control'] = 'no-store'
    response['Referrer-Policy'] = 'no-referrer'
    response['Content-Security-Policy'] = (
        f"default-src 'none'; script-src 'self' 'nonce-{nonce}'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'")
    return response


@require_GET
def asset(request, filename):
    enabled()
    allowed = {'swagger-ui-bundle.js': 'application/javascript', 'swagger-ui.css': 'text/css'}
    if filename not in allowed:
        raise Http404
    resource = files('drf_spectacular_sidecar').joinpath('static', 'drf_spectacular_sidecar',
                                                     'swagger-ui-dist', filename)
    response = FileResponse(resource.open('rb'), content_type=allowed[filename])
    response['Cache-Control'] = 'public, max-age=3600'
    return response
