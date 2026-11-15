import json
import re
from datetime import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from django.db import IntegrityError, transaction
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET
from .auth import api_endpoint
from .models import (
    Schedule,
    SyncRun,
    Event,
    EventVersion,
    AuditLog,
    ApiRequestLog,
    Coordinator,
)
from .scheduling import next_occurrence
from .services import audit, enqueue
from .sympla import configuration_error
from .sync_errors import message
from .provider_secrets import decrypt_token, ProviderSecretError


@require_GET
def ping(request):
    return HttpResponse("pong")


def body(request, allowed):
    if request.content_type != "application/json" or len(request.body) > 4096:
        raise ValueError("invalid_json_body")
    data = json.loads(request.body)
    if not isinstance(data, dict) or data.keys() - allowed:
        raise ValueError("unknown_fields")
    return data


def schedule_data(item):
    return {
        "id": item.id,
        "time": item.time.strftime("%H:%M"),
        "timezone": item.timezone,
        "active": item.active,
        "next_run_at": item.next_run_at if item.active else None,
        "created_at": item.created_at,
        "created_by": item.created_by,
    }


def page(request, queryset, fields):
    try:
        number = int(request.GET.get("page", "1"))
        size = int(request.GET.get("page_size", "50"))
        if not 1 <= number <= 100000 or not 1 <= size <= 100:
            raise ValueError()
    except ValueError:
        return JsonResponse({"error": "invalid_pagination"}, status=400)
    start = (number - 1) * size
    return JsonResponse(
        {
            "count": queryset.count(),
            "page": number,
            "page_size": size,
            "results": list(queryset.values(*fields)[start : start + size]),
        }
    )


@api_endpoint(["GET", "POST"])
def schedules(request):
    if request.method == "GET":
        query = Schedule.objects.filter(
            owner=request.api_user, deleted_at__isnull=True
        ).order_by("id")
        active = request.GET.get("active")
        if active is not None:
            if active not in ("true", "false"):
                return JsonResponse({"error": "invalid_active"}, status=400)
            query = query.filter(active=(active == "true"))
        try:
            number, size = int(request.GET.get("page", "1")), int(
                request.GET.get("page_size", "50")
            )
            if not 1 <= number <= 100000 or not 1 <= size <= 100:
                raise ValueError()
        except ValueError:
            return JsonResponse({"error": "invalid_pagination"}, status=400)
        return JsonResponse(
            {
                "count": query.count(),
                "results": [
                    schedule_data(s) for s in query[(number - 1) * size : number * size]
                ],
            }
        )
    try:
        data = body(request, {"time", "timezone", "active"})
        clock = data["time"]
        if not isinstance(clock, str) or not re.fullmatch(
            r"(?:[01]\d|2[0-3]):[0-5]\d", clock
        ):
            raise ValueError()
        zone = data["timezone"]
        if not isinstance(zone, str) or len(zone) > 100:
            raise ValueError()
        ZoneInfo(zone)
        active = data.get("active", True)
        if not isinstance(active, bool):
            raise ValueError()
        clock = time.fromisoformat(clock)
        with transaction.atomic():
            Coordinator.objects.select_for_update().get(pk=1)
            if (
                Schedule.objects.filter(
                    owner=request.api_user, deleted_at__isnull=True
                ).count()
                >= 100
            ):
                return JsonResponse({"error": "schedule_limit"}, status=409)
            item = Schedule.objects.create(
                owner=request.api_user,
                time=clock,
                timezone=zone,
                active=active,
                next_run_at=next_occurrence(clock, zone, timezone.now()),
                created_by=request.api_user.client_id,
            )
            audit(
                request.api_user.client_id,
                "schedule.created",
                "schedule",
                item.pk,
                {"time": data["time"], "timezone": zone, "active": active},
                request.interaction_id,
                owner=request.api_user,
            )
        return JsonResponse(schedule_data(item), status=201)
    except IntegrityError:
        return JsonResponse({"error": "duplicate_schedule"}, status=409)
    except (ValueError, KeyError, TypeError, ZoneInfoNotFoundError):
        return JsonResponse(
            {
                "error": "invalid_schedule",
                "required": "time HH:MM, timezone IANA, active boolean",
            },
            status=400,
        )


@api_endpoint(["DELETE", "PATCH"], write=True)
def schedule_detail(request, schedule_id):
    Coordinator.objects.select_for_update().get(pk=1)
    item = (
        Schedule.objects.select_for_update()
        .filter(owner=request.api_user, pk=schedule_id, deleted_at__isnull=True)
        .first()
    )
    if item is None:
        return JsonResponse({"error": "not_found"}, status=404)
    old = item.active
    if request.method == "DELETE":
        item.deleted_at, item.active = timezone.now(), False
        action, changes = "schedule.deleted", {
            "active": {"before": old, "after": False}
        }
    else:
        try:
            data = body(request, {"active"})
            if not isinstance(data["active"], bool):
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            return JsonResponse({"error": "invalid_active"}, status=400)
        item.active = data["active"]
        item.next_run_at = next_occurrence(item.time, item.timezone, timezone.now())
        action, changes = "schedule.updated", {
            "active": {"before": old, "after": item.active}
        }
    item.save()
    # Cancel pending occurrences, but leave an already-running sync to complete.
    if not item.active:
        for run in SyncRun.objects.select_for_update().filter(
            schedule=item, status="queued"
        ):
            run.status, run.finished_at = "cancelled", timezone.now()
            run.save(update_fields=["status", "finished_at"])
            audit(
                request.api_user.client_id,
                "sync.cancelled",
                "sync_run",
                run.pk,
                interaction=request.interaction_id,
                owner=request.api_user,
            )
    audit(
        request.api_user.client_id,
        action,
        "schedule",
        item.pk,
        changes,
        request.interaction_id,
        owner=request.api_user,
    )
    return (
        HttpResponse(status=204)
        if request.method == "DELETE"
        else JsonResponse(schedule_data(item))
    )


@api_endpoint(["POST"], write=True)
def sync_now(request):
    Coordinator.objects.select_for_update().get(pk=1)
    try:
        body(request, set())
    except (ValueError, TypeError):
        return JsonResponse({"error": "expected_empty_json_object"}, status=400)
    try:
        error = configuration_error(decrypt_token(request.api_user))
    except ProviderSecretError:
        error = "provider_secret_unavailable"
    if error:
        return JsonResponse({"error": error, "message": message(error)}, status=503)
    if SyncRun.objects.filter(
        owner=request.api_user, source="manual", status__in=["queued", "running"]
    ).exists():
        return JsonResponse({"error": "sync_pending"}, status=409)
    run = enqueue(
        request.api_user.client_id,
        interaction=request.interaction_id,
        owner=request.api_user,
    )
    return JsonResponse(
        {
            "id": str(run.pk),
            "status": run.status,
            "status_url": f"/api/v1/sync-runs/{run .pk }/",
            "message": "Synchronization queued. Check status_url for the result; events are available after success.",
        },
        status=202,
    )


@api_endpoint(["GET"])
def runs(request):
    return page(
        request,
        SyncRun.objects.filter(owner=request.api_user).order_by("-created_at"),
        [
            "id",
            "source",
            "actor",
            "schedule_id",
            "scheduled_for",
            "status",
            "created_at",
            "started_at",
            "finished_at",
            "error_code",
            "error_details",
            "counts",
        ],
    )


@api_endpoint(["GET"])
def run_detail(request, run_id):
    run = (
        SyncRun.objects.filter(owner=request.api_user, pk=run_id)
        .values(
            "id",
            "source",
            "actor",
            "schedule_id",
            "scheduled_for",
            "status",
            "created_at",
            "started_at",
            "finished_at",
            "error_code",
            "error_details",
            "counts",
        )
        .first()
    )
    if not run:
        return JsonResponse({"error": "not_found"}, status=404)
    if run["error_code"] and not run["error_details"]:
        run["error_details"] = {"message": message(run["error_code"])}
    return JsonResponse(run)


@api_endpoint(["GET"])
def events(request):
    return page(
        request,
        Event.objects.filter(owner=request.api_user).order_by("id"),
        ["id", "external_id", "version", "updated_at", "data"],
    )


@api_endpoint(["GET"])
def versions(request, event_id):
    if not Event.objects.filter(owner=request.api_user, pk=event_id).exists():
        return JsonResponse({"error": "not_found"}, status=404)
    return page(
        request,
        EventVersion.objects.filter(
            event__owner=request.api_user, event_id=event_id
        ).order_by("-version"),
        ["id", "version", "created_at", "run_id", "data", "differences"],
    )


@api_endpoint(["GET"])
def audit_logs(request):
    query = AuditLog.objects.order_by("-id")
    if not request.api_user.is_superuser:
        query = query.filter(owner_identifier=request.api_user.identifier)
    for field in ["resource", "target_id", "actor"]:
        if field in request.GET:
            query = query.filter(**{field: request.GET[field]})
    return page(
        request,
        query,
        [
            "id",
            "interaction_id",
            "created_at",
            "actor",
            "action",
            "resource",
            "target_id",
            "differences",
            "outcome",
        ],
    )


@api_endpoint(["GET"])
def request_logs(request):
    query = ApiRequestLog.objects.order_by("-id")
    if not request.api_user.is_superuser:
        query = query.filter(owner_identifier=request.api_user.identifier)
    return page(
        request,
        query,
        [
            "id",
            "interaction_id",
            "started_at",
            "finished_at",
            "actor",
            "method",
            "path",
            "http_status",
        ],
    )
