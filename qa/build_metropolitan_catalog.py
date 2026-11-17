"""Reproduce the capital scope from the official, pinned IBGE composition workbook."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE_URL = 'https://geoftp.ibge.gov.br/organizacao_do_territorio/estrutura_territorial/municipios_por_regioes_metropolitanas/Situacao_2020a2029/Composicao_RM_2025.xlsx'
CAPITAL_CODES = '''1100205 1200401 1302603 1400100 1501402 1600303 1721000 2111300 2211001
2304400 2408102 2507507 2611606 2704302 2800308 2927408 3106200 3205309 3304557
3550308 4106902 4205407 4314902 5002704 5103403 5208707 5300108'''.split()


def build(path):
    content = path.read_bytes()
    ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(path) as workbook:
        strings = [''.join(item.itertext()) for item in ET.fromstring(workbook.read('xl/sharedStrings.xml')).findall('m:si', ns)]
        rows = []
        for row in ET.fromstring(workbook.read('xl/worksheets/sheet1.xml')).findall('.//m:row', ns):
            values = {}
            for cell in row:
                value = cell.find('m:v', ns)
                if value is not None:
                    values[cell.attrib['r'].rstrip('0123456789')] = strings[int(value.text)] if cell.get('t') == 's' else value.text
            rows.append(values)
    assert rows[0]['M'] == 'COD_MUN' and rows[0]['G'] == 'COD_CATMETROPOL'
    rows = rows[1:]
    capitals, municipalities = [], {}
    # Rio Branco and Campo Grande have no metropolitan membership in this edition.
    standalone = {'1200401': ('Rio Branco', 'AC'), '5002704': ('Campo Grande', 'MS')}
    for code in CAPITAL_CODES:
        memberships = [row for row in rows if row.get('M') == code]
        categories = {row['G'] for row in memberships}
        selected = [row for row in rows if row.get('G') in categories]
        if memberships:
            name, state = memberships[0]['N'], memberships[0]['C']
        else:
            name, state = standalone[code]
        municipalities[code] = {'code': code, 'name': name, 'state': state}
        for row in selected:
            municipalities[row['M']] = {'code': row['M'], 'name': row['N'], 'state': row['C']}
        capitals.append({'code': code, 'name': name, 'state': state,
            'areas': [{'code': category, 'name': next(row['H'] for row in selected if row['G'] == category),
                       'members': sorted({row['M'] for row in selected if row['G'] == category}),
                       'subcategories': sorted({row['K'] for row in selected if row['G'] == category and row['K'] != 'NÃO TEM'})}
                      for category in sorted(categories)]})
    result = {'preset': 'capital_metropolitan_areas_2025', 'composition_year': 2025,
        'source_updated': '2026-07-29', 'source_url': SOURCE_URL,
        'source_sha256': hashlib.sha256(content).hexdigest(), 'capitals': capitals,
        'municipalities': sorted(municipalities.values(), key=lambda row: row['code'])}
    target = ROOT/'ticketing_sympla_app/core/integration_modules/ibge/metropolitan_areas_2025.json'
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(f"Catalog: {len(capitals)} capitals, {len(municipalities)} unique municipalities.")
    for capital in capitals:
        print(capital['state'], capital['name'], len({code for area in capital['areas'] for code in area['members']} or {capital['code']}))


if __name__ == '__main__':
    build(ROOT/'.qa-local/metro-2025.xlsx')
