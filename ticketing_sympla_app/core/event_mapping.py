"""Canonical event mapping and relational projections; no credential fields are retained."""
from .sympla import SyncError
from .models import EventAddress, EventHost, EventCategory

EVENT_FIELDS = {
    "id",
    "reference_id",
    "name",
    "detail",
    "start_date",
    "end_date",
    "published",
    "cancelled",
    "private_event",
    "url",
    "image",
}
NESTED_FIELDS = {
    "address": {
        "name",
        "address",
        "address_alt",
        "address_num",
        "neighborhood",
        "city",
        "state",
        "zip_code",
        "country",
        "lat",
        "lon",
    },
    "host": {"name", "description"},
    "category_prim": {"name"},
    "category_sec": {"name"},
}


def normalize(payload):
    # Persist only documented event fields; arbitrary upstream credential fields are excluded.
    if not isinstance(payload, dict) or 'id' not in payload or isinstance(payload['id'], (dict, list, bool)) or payload['id'] is None or not 1 <= len(str(payload['id'])) <= 200:
        raise SyncError('upstream_invalid_event')
    result = {key: value for key, value in payload.items() if key in EVENT_FIELDS}
    if any(isinstance(value, (dict, list)) for value in result.values()):
        raise SyncError("upstream_invalid_event")
    for key, allowed in NESTED_FIELDS.items():
        if key in payload:
            nested = payload[key]
            if nested is not None and not isinstance(nested, dict):
                raise SyncError("upstream_invalid_event")
            result[key] = (
                None
                if nested is None
                else {k: v for k, v in nested.items() if k in allowed}
            )
            if nested and any(
                isinstance(v, (dict, list)) for k, v in nested.items() if k in allowed
            ):
                raise SyncError("upstream_invalid_event")
    result["id"] = str(result["id"])
    return result



def project(event, data):
    for field in ('name', 'reference_id', 'detail', 'start_date', 'end_date', 'url', 'image'):
        value = data.get(field)
        setattr(event, field, '' if value is None else str(value))
    for field in ('published', 'cancelled', 'private_event'):
        value = data.get(field)
        if value is not None and value not in (True, False, 0, 1):
            raise SyncError('upstream_invalid_event')
        setattr(event, field, None if value is None else bool(value))
    if len(event.start_date) > 64 or len(event.end_date) > 64:
        raise SyncError('upstream_invalid_event')
    event.save()
    for key, model in [('address', EventAddress), ('host', EventHost)]:
        nested = data.get(key)
        if not nested:
            model.objects.filter(event=event).delete()
        else:
            fields = {field: '' if nested.get(field) is None else str(nested[field]) for field in NESTED_FIELDS[key]}
            model.objects.update_or_create(event=event, defaults=fields)
    for key, kind in [('category_prim', 'primary'), ('category_sec', 'secondary')]:
        nested = data.get(key)
        if not nested:
            EventCategory.objects.filter(event=event, kind=kind).delete()
        else:
            EventCategory.objects.update_or_create(event=event, kind=kind, defaults={'name': str(nested.get('name') or '')})
