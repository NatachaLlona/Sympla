import hashlib
import uuid
from functools import wraps
from django.db import transaction
from django.core.exceptions import RequestDataTooBig
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from .models import ApiUser, ApiRequestLog


def api_endpoint(methods, write=False):
    def decorate(view):
        @csrf_exempt  # Bearer-only: sessions and cookies cannot authorize API access.
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            started = timezone.now()
            request.interaction_id = uuid.uuid4()
            actor = ''
            with transaction.atomic():
                header = request.headers.get('Authorization', '')
                user = None
                if header.startswith('Bearer ') and len(header) <= 256:
                    digest = hashlib.sha256(header[7:].encode()).hexdigest()
                    user = ApiUser.objects.select_for_update().filter(token_hash=digest, is_active=True).first()
                if not user:
                    response = JsonResponse({'error': 'unauthorized'}, status=401)
                    response['WWW-Authenticate'] = 'Bearer'
                else:
                    actor = user.username
                    request.api_user = user
                    if write and not user.can_write:
                        response = JsonResponse({'error': 'forbidden'}, status=403)
                    elif request.method not in methods:
                        response = JsonResponse({'error': 'method_not_allowed'}, status=405)
                        response['Allow'] = ', '.join(methods)
                    else:
                        try:
                            with transaction.atomic():
                                response = view(request, *args, **kwargs)
                        except RequestDataTooBig:
                            response = JsonResponse({'error': 'request_too_large'}, status=413)
                        except Exception:
                            # Roll back mutations, then retain safe request evidence without a traceback/body.
                            response = JsonResponse({'error': 'internal_error'}, status=500)
                ApiRequestLog.objects.create(interaction_id=request.interaction_id,
                    started_at=started, finished_at=timezone.now(), actor=actor,
                    method=request.method, path=request.path[:200], http_status=response.status_code)
            response['X-Interaction-ID'] = str(request.interaction_id)
            response['Cache-Control'] = 'no-store'
            return response
        return wrapped
    return decorate
