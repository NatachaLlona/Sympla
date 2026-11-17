"""Build offline map assets from official IBGE 2022 cartography and municipal aggregates."""
import hashlib
import io
import json
from pathlib import Path
import urllib.request
import zipfile
import csv
import shapefile

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT/'.qa-local/map-sources'
SOURCES = {
    'states': 'https://geoftp.ibge.gov.br/organizacao_do_territorio/malhas_territoriais/malhas_municipais/municipio_2022/Brasil/BR/BR_UF_2022.zip',
    'seats': 'https://geoftp.ibge.gov.br/organizacao_do_territorio/estrutura_territorial/localidades/Localidades_do_Brasil/2022/Localidades_Brasil_shp.zip',
}


def simplify(points, tolerance=.025):
    if len(points) <= 4:
        return points
    # Iterative Douglas-Peucker; cartographic display only, never used to calculate areas.
    keep, stack = {0, len(points)-1}, [(0, len(points)-1)]
    while stack:
        start, end = stack.pop()
        ax, ay = points[start]; bx, by = points[end]
        dx, dy = bx-ax, by-ay
        length = dx*dx+dy*dy
        distance, farthest = 0, None
        for index in range(start+1, end):
            px, py = points[index]
            t = max(0, min(1, ((px-ax)*dx+(py-ay)*dy)/length)) if length else 0
            squared = (px-ax-t*dx)**2+(py-ay-t*dy)**2
            if squared > distance:
                distance, farthest = squared, index
        if distance > tolerance*tolerance:
            keep.add(farthest); stack.extend([(start, farthest), (farthest, end)])
    result = [[round(value, 5) for value in points[index]] for index in sorted(keep)]
    return result if len(result) >= 4 else [[round(value, 5) for value in point] for point in points[::max(1, len(points)//8)]]


def fetch(code, url):
    CACHE.mkdir(parents=True, exist_ok=True)
    target = CACHE/(code+'.zip')
    if not target.exists():
        with urllib.request.urlopen(url, timeout=90) as response:
            data = response.read(32*1024*1024+1)
        assert len(data) <= 32*1024*1024
        target.write_bytes(data)
    data = target.read_bytes()
    return data, {'url': url, 'sha256': hashlib.sha256(data).hexdigest(), 'reference_year': 2022}


def reader(data):
    archive = zipfile.ZipFile(io.BytesIO(data))
    parts = {Path(name).suffix: name for name in archive.namelist() if Path(name).suffix in ('.shp', '.shx', '.dbf')}
    return shapefile.Reader(**{extension[1:]: io.BytesIO(archive.read(name)) for extension, name in parts.items()}, encoding='utf-8')


def main():
    states_raw, states_source = fetch('states', SOURCES['states'])
    seats_raw, seats_source = fetch('seats', SOURCES['seats'])
    states = reader(states_raw)
    seats = reader(seats_raw)
    features = []
    for item in states.iterShapeRecords():
        row = item.record.as_dict()
        parts = list(item.shape.parts)+[len(item.shape.points)]
        rings = [simplify(item.shape.points[start:end]) for start, end in zip(parts, parts[1:])]
        rings = [ring if ring[-1] == ring[0] else ring+[ring[0]] for ring in rings if len(ring) >= 4]
        features.append({'type': 'Feature', 'properties': {'code': row['CD_UF'], 'name': row['NM_UF'], 'abbr': row['SIGLA_UF']},
                         'geometry': {'type': 'Polygon', 'coordinates': rings}})
    coordinates, candidates = {}, {}
    for item in seats.iterShapeRecords():
        row = item.record.as_dict()
        code = row['CD_LOCALID']
        level = 'city' if row['CT_LOCALID'] == 'Cidade' and len(code) == 7 else 'district' if row['CT_LOCALID'] == 'Vila' and len(code) == 9 else None
        if level:
            key = level+':'+code
            lon, lat = item.shape.points[0]
            candidates.setdefault(key, []).append((row['SCT_LOCALI'], {'latitude': round(lat, 6), 'longitude': round(lon, 6), 'coordinate_kind': 'municipal_seat' if level == 'city' else 'district_seat'}))
    for key, items in candidates.items():
        capitals = [item for kind, item in items if 'Capital' in kind]
        chosen = capitals or [item for _, item in items]
        if len(chosen) == 1:
            coordinates[key] = chosen[0]
        else:
            print('Ambiguous seat omitted:', key, len(chosen))
    provenance = {'coordinates': seats_source}
    for level in ('city', 'district', 'neighborhood'):
        import sys
        sys.path.insert(0, str(ROOT/'ticketing_sympla_app'))
        from core.integration_modules.ibge.catalog import archive
        url = archive(level, 'base')
        content, metadata = fetch(level+'_area', url)
        provenance[level+'_area'] = metadata
        with zipfile.ZipFile(io.BytesIO(content)) as zipped:
            raw = zipped.read(next(name for name in zipped.namelist() if name.endswith('.csv')))
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = raw.decode('cp1252')
        key_column = {'city': 'CD_MUN', 'district': 'CD_DIST', 'neighborhood': 'CD_BAIRRO'}[level]
        for row in csv.DictReader(io.StringIO(text), delimiter=';'):
            row = {key.upper(): value for key, value in row.items()}
            key = level+':'+row[key_column]
            entry = coordinates.setdefault(key, {})
            area = row.get('AREA_KM2', '').replace(',', '.')
            entry['area_km2'] = float(area) if area and float(area) > 0 else None
    public = ROOT/'audience-map/public/data'
    public.mkdir(exist_ok=True)
    (public/'brazil-states-2022.geojson').write_text(json.dumps({'type': 'FeatureCollection', 'source': states_source, 'features': features}, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    target = ROOT/'ticketing_sympla_app/core/integration_modules/ibge/map_reference_2022.json'
    target.write_text(json.dumps({'reference_year': 2022, 'sources': provenance, 'locations': coordinates}, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(f'Built {len(features)} state outlines and {len(coordinates)} spatial references; {sum("latitude" in item for item in coordinates.values())} official seats.')


if __name__ == '__main__':
    main()
