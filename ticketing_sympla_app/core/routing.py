"""Local-only OSRM accessibility; never substitute straight-line times for missing roads."""
import hashlib
import json
import math
import os
from pathlib import Path
import time
import requests
from django.core.cache import cache


def metadata():
    if os.getenv('ROUTING_ENABLED') != 'true':
        return {'status':'disabled'}
    path=Path('/routing-data/manifest.json')
    if not path.is_file():
        return {'status':'not_prepared'}
    try:
        data=json.loads(path.read_text(encoding='utf-8'))
        return {**data,'status':'ready','limitations':'Car-profile estimates to the event, without live traffic, parking time or public-transport schedules.'}
    except (ValueError,OSError):
        return {'status':'invalid_manifest'}


def travel_times(points, origin):
    meta=metadata()
    result={row['geography']['code']:None for row in points}
    if meta['status']!='ready':
        return result,meta
    west,south,east,north=meta['bbox']
    inside=lambda lat,lon: west<=lon<=east and south<=lat<=north
    if not inside(*origin):
        return result,{**meta,'status':'event_outside_coverage'}
    chosen=[row for row in points if inside(row['latitude'],row['longitude'])]
    deadline=time.monotonic()+12
    failures=max(0,len(chosen)-500)
    with requests.Session() as session:
        session.trust_env=False
        for start in range(0,min(len(chosen),500),50):
            chunk=chosen[start:start+50]
            key='local-routes:'+hashlib.sha256(json.dumps([meta['sha256'],origin,[(row['geography']['code'],row['latitude'],row['longitude']) for row in chunk]]).encode()).hexdigest()
            cached=cache.get(key)
            if cached is not None:
                result.update(cached);continue
            if time.monotonic()>deadline:
                failures+=len(chunk);continue
            positions=[f'{origin[1]},{origin[0]}']+[f"{row['longitude']},{row['latitude']}" for row in chunk]
            url='http://routing:5000/table/v1/driving/'+';'.join(positions)
            try:
                response=session.get(url,params={'sources':';'.join(str(index) for index in range(1,len(chunk)+1)),
                    'destinations':'0','annotations':'duration','radiuses':';'.join(['2000']*len(positions))},timeout=(2,5),allow_redirects=False)
                if response.status_code!=200 or len(response.content)>1024*1024:
                    raise ValueError()
                body=response.json()
                durations=body['durations']
                if body.get('code')!='Ok' or len(durations)!=len(chunk):raise ValueError()
                values={}
                for row,duration in zip(chunk,durations):
                    value=duration[0]
                    values[row['geography']['code']]=round(value/60,2) if isinstance(value,(int,float)) and math.isfinite(value) and value>=0 else None
                cache.set(key,values,3600);result.update(values)
            except (requests.RequestException,ValueError,KeyError,TypeError,IndexError):
                failures+=len(chunk)
    return result,{**meta,'status':'partial' if failures else 'ready','failed_locations':failures,'computed_locations':sum(value is not None for value in result.values())}
