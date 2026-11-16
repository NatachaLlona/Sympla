from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo


def next_occurrence(clock, zone_name, after):
    """Daily wall time: skip DST gaps; run ambiguous times at the first fold only."""
    zone = ZoneInfo(zone_name)
    day = after.astimezone(zone).date()
    for offset in range(370):
        naive = datetime.combine(day + timedelta(days=offset), clock)
        candidate = naive.replace(tzinfo=zone, fold=0).astimezone(dt_timezone.utc)
        if candidate.astimezone(zone).replace(tzinfo=None) != naive:
            continue
        if candidate > after:
            return candidate
    raise ValueError('No valid daily occurrence')
