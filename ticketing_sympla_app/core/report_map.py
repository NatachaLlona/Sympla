"""Offline SVG map for a captured, downloadable analysis report."""
import html
import json
import math
from pathlib import Path


def render(points):
    data = json.loads((Path(__file__).parent/'integration_modules/ibge/report_states_2022.geojson').read_text(encoding='utf-8'))
    project = lambda lon,lat: ((float(lon)+75)*18+20, (6-float(lat))*18+20)
    output = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 800" role="img" aria-label="Captured census audience map"><rect width="1000" height="800" fill="#eef5f5"/>']
    for state in data['features']:
        path = ''.join('M'+'L'.join(f'{x:.2f},{y:.2f}' for x,y in map(lambda p:project(*p),ring))+'Z' for ring in state['geometry']['coordinates'])
        output.append(f'<path d="{path}" fill="white" fill-rule="evenodd" stroke="#9ab5b8" stroke-width="0.6"/>')
    maximum = max([point['lower_bound'] for point in points]+[1])
    for point in points:
        x,y = project(point['longitude'],point['latitude']); radius=max(2,math.sqrt(point['lower_bound']/maximum)*16)
        color = '#929fa8' if point['match']=='incomplete_coverage' else '#0b8c80'
        output.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="{radius:.2f}" fill="{color}" opacity="0.7"><title>{html.escape(point["geography"]["name"])}: confirmed cohort {point["lower_bound"]}</title></circle>')
    return ''.join(output)+ '</svg><p><small>IBGE 2022 cartography. Bubble size: confirmed census-cohort lower bound; gray: incomplete coverage. Administrative-seat anchors, not household positions.</small></p>'
