"""Relational spatial metadata from pinned official IBGE sources."""
import json
from functools import lru_cache
from pathlib import Path
from .models import Geography, GeographyMapReference


@lru_cache(maxsize=1)
def catalog():
    return json.loads((Path(__file__).parent/'integration_modules/ibge/map_reference_2022.json').read_text(encoding='utf-8'))


def reference_data(geography):
    data = catalog()
    entry = data['locations'].get(geography.level+':'+geography.code)
    if not entry or geography.reference_year != data['reference_year']:
        return None
    return {**entry, 'reference_year': data['reference_year'], 'provenance': {
        'coordinates': data['sources']['coordinates'] if entry.get('latitude') is not None else None,
        'area': data['sources'].get(geography.level+'_area')}}


def populate():
    rows = []
    for geography in Geography.objects.all():
        data = reference_data(geography)
        if data:
            rows.append(GeographyMapReference(geography=geography, **data))
    GeographyMapReference.objects.bulk_create(rows, update_conflicts=True, unique_fields=['geography'],
        update_fields=['latitude', 'longitude', 'area_km2', 'coordinate_kind', 'reference_year', 'provenance'])
    return len(rows)
