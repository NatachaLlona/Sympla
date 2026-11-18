"""Prepare a reproducible local OSRM car graph; downloads never contain application secrets."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
IMAGE='ghcr.io/project-osrm/osrm-backend@sha256:e1929ae2818226284d7ef007329098a30851c11528ab3712bc9c8d68da78278b'
REGIONS={
    'rio-de-janeiro': ('https://download.bbbike.org/osm/bbbike/RiodeJaneiro/RiodeJaneiro.osm.pbf','https://download.bbbike.org/osm/bbbike/RiodeJaneiro/RiodeJaneiro.poly'),
    'sudeste': ('https://download.geofabrik.de/south-america/brazil/sudeste-latest.osm.pbf','https://download.geofabrik.de/south-america/brazil/sudeste.poly'),
    'brazil': ('https://download.geofabrik.de/south-america/brazil-latest.osm.pbf','https://download.geofabrik.de/south-america/brazil.poly'),
}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--region',choices=REGIONS,default='rio-de-janeiro');parser.add_argument('--memory',default='6g')
    args=parser.parse_args(); folder=ROOT/'routing/data'/args.region;folder.mkdir(parents=True,exist_ok=True)
    if (folder/'manifest.json').exists():
        print('Routing graph already prepared. Existing graph was preserved.');return
    url,poly=REGIONS[args.region]; target=folder/'region.osm.pbf'
    if not target.exists():
        partial=folder/'region.osm.pbf.partial'; size=0
        with urllib.request.urlopen(url,timeout=90) as response, partial.open('wb') as output:
            modified=response.headers.get('Last-Modified','unknown')
            while chunk:=response.read(1024*1024):
                size+=len(chunk)
                if size>3*1024**3:raise RuntimeError('Routing extract exceeds the documented 3 GiB download limit.')
                output.write(chunk)
                if size//(10*1024**2)!=(size-len(chunk))//(10*1024**2):print(f'Routing download: {size//1024**2} MiB',flush=True)
        partial.replace(target)
        (folder/'download.json').write_text(json.dumps({'url':url,'last_modified':modified}),encoding='utf-8')
    digest=hashlib.file_digest(target.open('rb'),'sha256').hexdigest()
    with urllib.request.urlopen(poly,timeout=30) as response:
        polygon=response.read(1024*1024).decode()
    points=[]
    for line in polygon.splitlines():
        try:
            values=list(map(float,line.split()))
            if len(values)==2:points.append(values)
        except ValueError:pass
    if not points:raise RuntimeError('No routing coverage polygon was published.')
    for stage,command in [('extract',['osrm-extract','--threads','2','-p','/opt/car.lua','/data/region.osm.pbf']),
                          ('partition',['osrm-partition','--threads','2','/data/region.osrm']),
                          ('customize',['osrm-customize','--threads','2','/data/region.osrm'])]:
        marker=folder/(stage+'.complete')
        if not marker.exists():
            print('Preparing local routing stage: '+stage,flush=True)
            subprocess.run(['docker','run','--rm','--read-only','--tmpfs','/tmp','--cap-drop','ALL','--security-opt','no-new-privileges:true','--memory',args.memory,'--cpus','2','--mount',f'type=bind,source={folder},target=/data',IMAGE,*command],check=True)
            marker.write_text(digest,encoding='utf-8')
    metadata=json.loads((folder/'download.json').read_text(encoding='utf-8'))
    metadata.update({'region':args.region,'sha256':digest,'engine_image':IMAGE,'profile':'car','live_traffic':False,
        'bbox':[min(p[0] for p in points),min(p[1] for p in points),max(p[0] for p in points),max(p[1] for p in points)],
        'prepared_at':datetime.now(timezone.utc).isoformat(),'attribution':'© OpenStreetMap contributors; extract provider BBBike/Geofabrik; ODbL'})
    (folder/'manifest.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    print('Local routing graph ready: '+args.region,flush=True)


if __name__=='__main__':main()
