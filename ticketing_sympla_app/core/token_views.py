import base64
import hashlib
import json
import secrets
import uuid
from datetime import timedelta
from urllib.parse import unquote
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import RequestDataTooBig
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from .models import ApiUser, AccessToken, TokenThrottle, ApiRequestLog

DUMMY_HASH = make_password("dummy-value-never-a-real-client-secret")


@csrf_exempt
def token(request):
    started, interaction = timezone.now(), uuid.uuid4()
    actor = ""
    with transaction.atomic():
        key = hashlib.sha256(
            (request.META.get("REMOTE_ADDR", "") or "unknown").encode()
        ).hexdigest()
        TokenThrottle.objects.get_or_create(
            key=key, defaults={"window_started": started}
        )
        throttle = TokenThrottle.objects.select_for_update().get(key=key)
        if started - throttle.window_started >= timedelta(minutes=1):
            throttle.window_started, throttle.attempts = started, 0
        throttle.attempts += 1
        throttle.save()
        if request.method != "POST":
            result = JsonResponse({"error": "method_not_allowed"}, status=405)
            result["Allow"] = "POST"
        elif throttle.attempts > 10:
            result = JsonResponse({"error": "rate_limited"}, status=429)
            result["Retry-After"] = "60"
        else:
            try:
                if len(request.body) > 4096:
                    raise ValueError()
                if request.content_type == "application/json":
                    data = json.loads(request.body)
                elif request.content_type == "application/x-www-form-urlencoded":
                    if any(len(values) != 1 for _, values in request.POST.lists()):
                        raise ValueError()
                    data = request.POST.dict()
                else:
                    raise ValueError()
                if not isinstance(data, dict) or data.keys() - {
                    "grant_type",
                    "client_id",
                    "client_secret",
                    "scope",
                }:
                    raise ValueError()
                if data.get("grant_type") != "client_credentials":
                    raise ValueError()
                if data.get("scope", "") != "":
                    raise ValueError()
                client_id, secret = data.get("client_id", ""), data.get(
                    "client_secret", ""
                )
                authorization = request.headers.get("Authorization", "")
                if authorization:
                    if (
                        not authorization.startswith("Basic ")
                        or client_id
                        or secret
                        or len(authorization) > 1024
                    ):
                        raise ValueError()
                    pair = (
                        base64.b64decode(authorization[6:], validate=True)
                        .decode("utf-8")
                        .split(":", 1)
                    )
                    client_id, secret = (unquote(value) for value in pair)
                if (
                    not isinstance(client_id, str)
                    or not isinstance(secret, str)
                    or len(client_id) > 100
                    or len(secret) > 256
                ):
                    raise ValueError()
            except RequestDataTooBig:
                result = JsonResponse({"error": "request_too_large"}, status=413)
            except (ValueError, TypeError, UnicodeError):
                result = JsonResponse({"error": "invalid_request"}, status=400)
            else:
                user = (
                    ApiUser.objects.select_for_update()
                    .filter(username=client_id)
                    .first()
                )
                valid = check_password(
                    secret,
                    (
                        user.client_secret_hash
                        if user and user.client_secret_hash
                        else DUMMY_HASH
                    ),
                )
                if not user or not valid or not user.is_active or user.deleted_at:
                    result = JsonResponse({"error": "invalid_client"}, status=401)
                    result["WWW-Authenticate"] = 'Basic realm="token"'
                else:
                    actor = user.username
                    AccessToken.objects.filter(
                        user=user, expires_at__lte=started
                    ).delete()
                    value = secrets.token_urlsafe(48)
                    ttl = settings.API_TOKEN_TTL_SECONDS
                    AccessToken.objects.create(
                        token_hash=hashlib.sha256(value.encode()).hexdigest(),
                        user=user,
                        credential_version=user.credential_version,
                        expires_at=started + timedelta(seconds=ttl),
                    )
                    result = JsonResponse(
                        {
                            "access_token": value,
                            "token_type": "Bearer",
                            "expires_in": ttl,
                        }
                    )
        ApiRequestLog.objects.create(
            owner_identifier=user.identifier if actor else None,
            interaction_id=interaction,
            started_at=started,
            finished_at=timezone.now(),
            actor=actor,
            method=request.method,
            path=request.path,
            http_status=result.status_code,
        )
    result["Cache-Control"] = "no-store"
    result["Pragma"] = "no-cache"
    result["X-Interaction-ID"] = str(interaction)
    return result
