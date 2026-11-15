import hashlib
import uuid
from functools import wraps
from django.db import transaction, IntegrityError
from .api_errors import ApiProblem
from django.core.exceptions import RequestDataTooBig
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from .models import ApiUser, ApiRequestLog, AccessToken, Coordinator
from .rbac import METHOD_PERMISSION, permitted


def api_endpoint(methods, write=False, master=False, identity=False):
    def decorate(view):
        @csrf_exempt  # Bearer-only: sessions and cookies cannot authorize API access.
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            started = timezone.now()
            request.interaction_id = uuid.uuid4()
            actor = ''
            owner_identifier = None
            with transaction.atomic():
                Coordinator.objects.select_for_update().get(pk=1)
                header = request.headers.get('Authorization', '')
                user = None
                if header.startswith('Bearer ') and len(header) <= 256:
                    digest = hashlib.sha256(header[7:].encode()).hexdigest()
                    token = AccessToken.objects.filter(token_hash=digest, expires_at__gt=timezone.now()).first()
                    if token:
                        user = ApiUser.objects.select_for_update().filter(pk=token.user_id, is_active=True, deleted_at__isnull=True,
                            credential_version=token.credential_version).first()
                if not user:
                    response = JsonResponse({'error': 'unauthorized'}, status=401)
                    response['WWW-Authenticate'] = 'Bearer'
                else:
                    actor = user.username
                    owner_identifier = user.identifier
                    request.api_user = user
                    if master and not user.is_superuser:
                        response = JsonResponse({'error': 'forbidden'}, status=403)
                    elif request.method not in methods:
                        response = JsonResponse({'error': 'method_not_allowed'}, status=405)
                        response['Allow'] = ', '.join(methods)
                    elif not identity and not permitted(user, METHOD_PERMISSION.get(request.method, '')):
                        response = JsonResponse({'error': 'forbidden', 'required_permission': METHOD_PERMISSION.get(request.method)}, status=403)
                    else:
                        try:
                            with transaction.atomic():
                                response = view(request, *args, **kwargs)
                        except RequestDataTooBig:
                            response = JsonResponse({'error': 'request_too_large'}, status=413)
                        except ApiProblem as exc:
                            response = JsonResponse({'error': exc.code, 'message': exc.message}, status=exc.status)
                        except IntegrityError:
                            response = JsonResponse({'error': 'conflict', 'message': 'The record conflicts with an existing record or relationship.'}, status=409)
                        except Exception:
                            # Roll back mutations, then retain safe request evidence without a traceback/body.
                            response = JsonResponse({'error': 'internal_error'}, status=500)
                ApiRequestLog.objects.create(interaction_id=request.interaction_id,
                    owner_identifier=owner_identifier,
                    started_at=started, finished_at=timezone.now(), actor=actor,
                    method=request.method, path=request.path[:200], http_status=response.status_code)
            response['X-Interaction-ID'] = str(request.interaction_id)
            response['Cache-Control'] = 'no-store'
            return response
        return wrapped
    return decorate
