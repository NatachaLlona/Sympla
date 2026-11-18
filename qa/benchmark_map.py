"""Run inside manage.py shell; prints timings/counts only, never credentials or source records."""
import inspect
import json
import statistics
import time
from django.test import RequestFactory
from django.db import connection
from core.models import ApiUser, Integration
from core.map_views import map_data


def benchmark(client_id):
    account=ApiUser.objects.get(client_id=client_id)
    integration=Integration.objects.get(owner=account,configuration__geographic_preset='capital_metropolitan_areas_2025')
    samples=[]
    for iteration in range(5):
        count=[0]
        def measure(execute,sql,params,many,context):
            count[0]+=1
            return execute(sql,params,many,context)
        request=RequestFactory().get('/api/v1/demographics/map/',{'integration_id':str(integration.pk),'target_year':'2026','age_min':'4','age_max':'8','level':'city'})
        request.api_user=account
        with connection.execute_wrapper(measure):
            start=time.perf_counter();response=inspect.unwrap(map_data)(request);elapsed=time.perf_counter()-start
        body=json.loads(response.content)
        assert body['count']==430
        samples.append({'milliseconds':round(elapsed*1000,2),'queries':count[0],'response_bytes':len(response.content)})
    print(json.dumps({'client_scope':'owned-national-source','locations':430,'samples':samples,
                      'warm_median_ms':round(statistics.median(row['milliseconds'] for row in samples[1:]),2)}))
