"""Owned sales uploads, reproducible analysis scenarios, reports and in-app alerts."""
import copy
import csv
import hashlib
import html
import inspect
import io
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from django.db.models import Count, Max, Sum
from django.http import JsonResponse, HttpResponse, QueryDict
from django.utils import timezone
from .api_errors import ApiProblem
from .auth import api_endpoint
from .identity import payload, collection
from .models import (Event, Geography, Statistic, SyncRun, Sale, SalesUpload, SaleVersion, ImportSource,
    AnalysisScenario, ScenarioSnapshot, AnalysisNote, AnalysisAlert)
from .rbac import permitted
from .services import audit

CSV_COLUMNS = ['sale_id', 'sold_on', 'municipality_code', 'tickets', 'revenue']


def require(api_account, *permissions):
    if not all(permitted(api_account, value) for value in permissions):
        raise ApiProblem('forbidden', 'Required permissions: '+', '.join(permissions), 403)


def text(value, name, maximum=120):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(char) < 32 and not (name=='text' and char in '\r\n\t') for char in value):
        raise ApiProblem('invalid_request', f'{name} must be printable text, 1–{maximum} characters.')
    return value.strip()


def owned_event(api_account, value):
    if not str(value).isascii() or not str(value).isdigit() or len(str(value)) > 18:
        raise ApiProblem('invalid_event', 'Choose an event database identifier.')
    event = Event.objects.filter(owner=api_account, pk=value).first()
    if not event:
        raise ApiProblem('not_found', 'Event not found.', 404)
    return event


def signature(api_account):
    from .routing import metadata
    values = [Statistic.objects.filter(integration__owner=api_account).aggregate(count=Count('pk'), latest=Max('last_seen_at'), versions=Sum('version')),
              Sale.objects.filter(owner=api_account).aggregate(count=Count('pk'), versions=Sum('version'), upload=Max('last_upload_id')),
              Event.objects.filter(owner=api_account).aggregate(count=Count('pk'), latest=Max('updated_at'))]
    values.append(metadata().get('sha256'))
    return hashlib.sha256(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()


def map_result(api_account, filters):
    from django.test.client import RequestFactory
    from .map_views import map_data
    require(api_account, 'demographics:read')
    if not isinstance(filters, dict) or len(filters) > 30 or any(not isinstance(key, str) or not isinstance(value, (str, int, float, bool)) for key, value in filters.items()):
        raise ApiProblem('invalid_filters', 'Provide flat, documented map filters.')
    # Capture the complete source scope, independent of the current viewport or display zoom.
    filters = {key: str(value).lower() if type(value) is bool else str(value) for key, value in filters.items() if key not in ('bbox', 'zoom', 'detail')}
    request = RequestFactory().get('/api/v1/demographics/map/', filters)
    request.api_user = api_account
    response = inspect.unwrap(map_data)(request)
    result = json.loads(response.content)
    if response.status_code != 200:
        raise ApiProblem(result.get('error', 'invalid_filters'), result.get('message', 'Map filters are not authorized.'), response.status_code)
    run_ids={band['last_run_id'] for point in result['results'] for band in point['bands'] if band.get('last_run_id')}
    artifacts=list(ImportSource.objects.filter(run_id__in=run_ids,run__owner=api_account).values('id','code','url','sha256','reference_period','run_id','collected_at'))
    result['source_artifacts']=json.loads(json.dumps(artifacts,default=str))
    if filters.get('event_id') and permitted(api_account,'sales:read'):
        sales=Sale.objects.filter(owner=api_account,event_id=filters['event_id'])
        result['uploaded_sales']=json.loads(json.dumps({'totals':sales.aggregate(records=Count('pk'),tickets=Sum('tickets'),revenue=Sum('revenue')),
            'by_origin':list(sales.values('municipality_code','edition').annotate(tickets=Sum('tickets'),revenue=Sum('revenue'))),
            'uploads':list(SalesUpload.objects.filter(owner=api_account,event_id=filters['event_id']).values('id','sha256','edition','created_at'))},default=str))
    return result


def scenario_for(request, pk):
    result = AnalysisScenario.objects.filter(owner=request.api_user, pk=pk, deleted_at__isnull=True).first()
    if not result:
        raise ApiProblem('not_found', 'Scenario not found.', 404)
    return result


def scenario_data(row):
    return {'id': row.pk, 'name': row.name, 'filters': row.filters, 'revision': row.revision, 'watch': row.watch,
            'created_at': row.created_at, 'updated_at': row.updated_at}


@api_endpoint(['GET', 'POST'], section='sales')
def uploads(request):
    require(request.api_user, 'events:read')
    if request.method == 'GET':
        return collection(request, SalesUpload.objects.filter(owner=request.api_user).order_by('-pk'),
            lambda row: {'id': row.pk, 'event_id': row.event_id, 'edition': row.edition, 'sha256': row.sha256,
                         'row_count': row.row_count, 'counts': row.counts, 'created_at': row.created_at})
    if request.content_type != 'multipart/form-data' or set(request.POST) != {'event_id', 'edition'} or set(request.FILES) != {'file'}:
        raise ApiProblem('invalid_upload', 'Send multipart fields event_id, edition and one CSV file named file.')
    event = owned_event(request.api_user, request.POST['event_id'])
    edition = text(request.POST['edition'], 'edition', 80)
    file = request.FILES['file']
    if file.size > 5*1024*1024 or not file.size:
        raise ApiProblem('upload_limit', 'Upload a nonempty UTF-8 CSV up to 5 MiB and 10000 rows.')
    content = file.read(5*1024*1024+1)
    digest = hashlib.sha256(content).hexdigest()
    previous = SalesUpload.objects.filter(owner=request.api_user, event=event, edition=edition, sha256=digest).first()
    if previous:
        return JsonResponse({'id': previous.pk, 'duplicate': True, 'counts': previous.counts})
    try:
        reader = csv.DictReader(io.StringIO(content.decode('utf-8-sig'), newline=''))
        if reader.fieldnames != CSV_COLUMNS:
            raise ValueError('Use exactly these CSV columns, in order: '+','.join(CSV_COLUMNS))
        rows, seen = [], set()
        for index, row in enumerate(reader, 2):
            if index > 10001:
                raise ValueError('CSV exceeds 10000 data rows.')
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f'Row {index}: incorrect column count.')
            external_id = row['sale_id'].strip()
            if not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,100}', external_id) or external_id in seen:
                raise ValueError(f'Row {index}: sale_id must be unique in the file and contain 1–100 identifier characters.')
            seen.add(external_id)
            sold_on = date.fromisoformat(row['sold_on'])
            if sold_on > timezone.localdate() or sold_on.year < 2000:
                raise ValueError(f'Row {index}: sold_on must be an ISO date between 2000 and today.')
            code = row['municipality_code'].strip()
            if code and not re.fullmatch(r'[0-9]{7}', code):
                raise ValueError(f'Row {index}: municipality_code must be blank or a 7-digit IBGE code.')
            if not re.fullmatch(r'[0-9]{1,7}', row['tickets']) or int(row['tickets']) > 1000000:
                raise ValueError(f'Row {index}: tickets must be an integer from 0 to 1000000.')
            if not re.fullmatch(r'[0-9]{1,12}(\.[0-9]{1,2})?', row['revenue']):
                raise ValueError(f'Row {index}: revenue must be nonnegative BRL with a decimal point and at most 2 decimals.')
            rows.append({'external_id': external_id, 'sold_on': sold_on.isoformat(), 'municipality_code': code,
                         'tickets': int(row['tickets']), 'revenue': str(Decimal(row['revenue']).quantize(Decimal('.01')))})
        if not rows:
            raise ValueError('CSV must contain at least one data row.')
    except (UnicodeError, csv.Error, ValueError, InvalidOperation) as error:
        raise ApiProblem('invalid_csv', str(error) if not isinstance(error, UnicodeError) else 'CSV must use UTF-8 encoding.') from None
    cities = {row.code: row for row in Geography.objects.filter(level='city', reference_year=2022)}
    upload = SalesUpload.objects.create(owner=request.api_user, event=event, edition=edition, sha256=digest, row_count=len(rows))
    counts = {'created': 0, 'updated': 0, 'unchanged': 0, 'unresolved_origin': 0}
    existing = {row.external_id: row for row in Sale.objects.filter(owner=request.api_user, event=event, edition=edition, external_id__in=seen)}
    new_sales, updated_sales, versions = [], [], []
    for row in rows:
        fingerprint = hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()
        sale = existing.get(row['external_id'])
        if row['municipality_code'] not in cities:
            counts['unresolved_origin'] += 1
        if sale and sale.fingerprint == fingerprint:
            counts['unchanged'] += 1
            continue
        if sale:
            sale.version += 1
            counts['updated'] += 1
        else:
            sale = Sale(owner=request.api_user, event=event, edition=edition, external_id=row['external_id'])
            counts['created'] += 1
        for key in ('sold_on', 'municipality_code', 'tickets', 'revenue'):
            setattr(sale, key, row[key])
        sale.geography = cities.get(row['municipality_code'])
        sale.fingerprint, sale.last_upload = fingerprint, upload
        (updated_sales if sale.pk else new_sales).append(sale)
        versions.append((sale,row))
    Sale.objects.bulk_create(new_sales,batch_size=500)
    Sale.objects.bulk_update(updated_sales,['sold_on','municipality_code','tickets','revenue','geography','fingerprint','last_upload','version'],batch_size=500)
    SaleVersion.objects.bulk_create([SaleVersion(sale=sale,upload=upload,version=sale.version,snapshot=row) for sale,row in versions],batch_size=500)
    upload.counts = counts
    upload.save(update_fields=['counts'])
    audit(request.api_user.client_id, 'sales.uploaded', 'sales_upload', upload.pk, {'sha256': digest, **counts}, owner=request.api_user)
    return JsonResponse({'id': upload.pk, 'duplicate': False, 'counts': counts}, status=201)


@api_endpoint(['GET'], section='sales')
def sales_summary(request):
    require(request.api_user, 'events:read')
    event = owned_event(request.api_user, request.GET.get('event_id', ''))
    query = Sale.objects.filter(owner=request.api_user, event=event)
    if request.GET.get('edition'):
        query = query.filter(edition=request.GET['edition'])
    by_origin = list(query.values('municipality_code', 'geography__name').annotate(tickets=Sum('tickets'), revenue=Sum('revenue')).order_by('-tickets'))
    editions = list(query.values('edition').annotate(tickets=Sum('tickets'), revenue=Sum('revenue'), records=Count('pk')).order_by('edition'))
    return JsonResponse({'event_id': event.pk, 'by_origin': by_origin, 'editions': editions,
        'totals': query.aggregate(tickets=Sum('tickets'), revenue=Sum('revenue'), records=Count('pk')),
        'limitations': 'Uploaded records only. Missing origins and absent uploads are not proof of zero sales. Buyer age/income and campaign attribution are not collected.'})


@api_endpoint(['GET', 'POST'], section='scenarios')
def scenarios(request):
    if request.method == 'GET':
        return collection(request, AnalysisScenario.objects.filter(owner=request.api_user, deleted_at__isnull=True).order_by('-pk'), scenario_data)
    data = payload(request, ['name', 'filters', 'watch'], ['name', 'filters'])
    if type(data.get('watch', False)) is not bool:
        raise ApiProblem('invalid_request', 'watch must be a boolean.')
    name = text(data['name'], 'name')
    result = map_result(request.api_user, data['filters'])
    if AnalysisScenario.objects.filter(owner=request.api_user, deleted_at__isnull=True).count() >= 100:
        raise ApiProblem('scenario_limit', 'A maximum of 100 active scenarios is allowed.')
    row = AnalysisScenario.objects.create(owner=request.api_user, name=name, filters=data['filters'], watch=data.get('watch', False))
    snapshot = ScenarioSnapshot.objects.create(scenario=row, scenario_revision=row.revision, filters=row.filters,
        result=result, source_signature=signature(request.api_user))
    audit(request.api_user.client_id, 'scenario.created', 'scenario', row.pk, {'snapshot_id': snapshot.pk}, owner=request.api_user)
    return JsonResponse({**scenario_data(row), 'snapshot_id': snapshot.pk}, status=201)


@api_endpoint(['GET', 'PATCH', 'DELETE'], section='scenarios')
def scenario_detail(request, pk):
    row = scenario_for(request, pk)
    if request.method == 'DELETE':
        row.deleted_at = timezone.now(); row.watch = False
    elif request.method == 'PATCH':
        data = payload(request, ['name', 'filters', 'watch'])
        if 'name' in data:
            row.name = text(data['name'], 'name')
        if 'filters' in data:
            map_result(request.api_user, data['filters']); row.filters = data['filters']
        if 'watch' in data:
            if type(data['watch']) is not bool:
                raise ApiProblem('invalid_request', 'watch must be a boolean.')
            row.watch = data['watch']
        row.revision += 1
    if request.method != 'GET':
        row.updated_at = timezone.now(); row.save()
        audit(request.api_user.client_id, 'scenario.'+request.method.lower(), 'scenario', row.pk, {'revision': row.revision}, owner=request.api_user)
    return JsonResponse(scenario_data(row))


@api_endpoint(['GET', 'POST'], section='scenarios')
def snapshots(request, pk):
    row = scenario_for(request, pk)
    if row.filters.get('event_id'):
        require(request.api_user, 'events:read')
    if request.method == 'POST':
        result = map_result(request.api_user, row.filters)
        snapshot = ScenarioSnapshot.objects.create(scenario=row, scenario_revision=row.revision, filters=row.filters,
            result=result, source_signature=signature(request.api_user))
        audit(request.api_user.client_id, 'scenario.captured', 'scenario', row.pk, {'snapshot_id': snapshot.pk}, owner=request.api_user)
        return JsonResponse({'id': snapshot.pk, 'created_at': snapshot.created_at}, status=201)
    return collection(request, ScenarioSnapshot.objects.filter(scenario=row).order_by('-pk'),
        lambda item: {'id': item.pk, 'scenario_revision': item.scenario_revision, 'filters': item.filters,
                      'source_signature': item.source_signature, 'created_at': item.created_at, 'mapped_locations': item.result['count']})


@api_endpoint(['GET'], section='reports')
def report(request, pk):
    require(request.api_user, 'scenarios:read', 'demographics:read')
    row = scenario_for(request, pk)
    snapshot = ScenarioSnapshot.objects.filter(scenario=row).order_by('-pk').first()
    if not snapshot:
        raise ApiProblem('not_found', 'Capture a scenario before exporting.', 404)
    if snapshot.filters.get('event_id'):
        require(request.api_user, 'events:read')
    if request.GET.get('snapshot_id'):
        if not request.GET['snapshot_id'].isascii() or not request.GET['snapshot_id'].isdigit() or len(request.GET['snapshot_id'])>18:
            raise ApiProblem('invalid_identifier','snapshot_id must be a positive database identifier.')
        snapshot = ScenarioSnapshot.objects.filter(pk=request.GET['snapshot_id'], scenario=row).first()
        if not snapshot:
            raise ApiProblem('not_found', 'Snapshot not found.', 404)
    if 'uploaded_sales' in snapshot.result:
        require(request.api_user,'sales:read','events:read')
    if request.GET.get('format', 'json') == 'json':
        return JsonResponse({'scenario': scenario_data(row), 'snapshot_id': snapshot.pk, 'captured_at': snapshot.created_at,
            'source_signature': snapshot.source_signature, 'filters': snapshot.filters, 'result': snapshot.result})
    if request.GET['format'] != 'html':
        raise ApiProblem('invalid_format', 'Choose json or html.')
    esc = lambda value: html.escape(str(value))
    result = snapshot.result
    from .report_map import render
    lines = ['<!doctype html><html lang="en"><meta charset="utf-8"><title>Audience report</title>',
        '<style>body{font:15px system-ui;max-width:1100px;margin:40px auto;color:#193e48}table{width:100%;border-collapse:collapse}td,th{padding:9px;border-bottom:1px solid #ddd;text-align:left}pre{white-space:pre-wrap}small{color:#567}</style>',
        '<h1>'+esc(row.name)+'</h1>', '<p>Captured '+esc(snapshot.created_at)+' · Snapshot '+str(snapshot.pk)+'</p>',
        '<h2>Filters and reference</h2><pre>'+esc(json.dumps(snapshot.filters, indent=2))+'</pre>',
        '<h2>Coverage</h2><pre>'+esc(json.dumps(result['coverage'], indent=2))+'</pre>',
        '<h2>Captured audience map</h2>'+render(result['results']),
        '<h2>Locations</h2><table><tr><th>Location</th><th>Lower count</th><th>Upper count</th><th>Estimate</th><th>Area km²</th><th>Income BRL 2022</th><th>Car minutes</th></tr>']
    for point in result['results']:
        lines.append('<tr>'+''.join('<td>'+esc(value if value is not None else 'Unknown')+'</td>' for value in [
            point['geography']['name'], point['lower_bound'], point['upper_bound'], point['estimated_count'], point['area_km2'], point['income']['value'],point.get('travel_minutes')])+'</tr>')
    lines.append('</table>')
    if result.get('max_travel_minutes') is not None:
        lines.append('<h2>Local routing provenance</h2><pre>'+esc(json.dumps(result.get('routing',{}),indent=2))+'</pre>')
    lines += ['<h2>Source artifacts</h2><ul>']+['<li>'+esc(source['code'])+' · '+esc(source['url'])+' · SHA-256 '+esc(source['sha256'])+'</li>' for source in result.get('source_artifacts',[])]+['</ul><h2>Limitations</h2><ul>']+['<li>'+esc(item)+'</li>' for item in result['limitations']]+['</ul><p>Source signature: '+esc(snapshot.source_signature)+'</p><p>Export JSON for the complete source IDs, versions and provenance. Print this document to PDF if needed.</p></html>']
    response = HttpResponse(''.join(lines), content_type='text/html; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="audience-report-{row.pk}-{snapshot.pk}.html"'
    return response


@api_endpoint(['GET', 'POST'], section='scenarios')
def notes(request):
    if request.method == 'GET':
        return collection(request, AnalysisNote.objects.filter(owner=request.api_user).order_by('-pk'),
            lambda row: {'id': row.pk, 'scenario_id': row.scenario_id, 'geography_id': row.geography_id, 'text': row.text, 'created_at': row.created_at})
    data = payload(request, ['text', 'scenario_id', 'geography_id'], ['text'])
    scenario = scenario_for(request, data['scenario_id']) if data.get('scenario_id') else None
    geography = Geography.objects.filter(pk=data['geography_id'], statistic__integration__owner=request.api_user).distinct().first() if data.get('geography_id') else None
    if data.get('geography_id') and not geography:
        raise ApiProblem('not_found', 'Owned geography not found.', 404)
    row = AnalysisNote.objects.create(owner=request.api_user, scenario=scenario, geography=geography, text=text(data['text'], 'text', 2000))
    audit(request.api_user.client_id, 'analysis.note_created', 'analysis_note', row.pk, owner=request.api_user)
    return JsonResponse({'id': row.pk}, status=201)


@api_endpoint(['GET'], section='scenarios')
def alerts(request):
    return collection(request, AnalysisAlert.objects.filter(scenario__owner=request.api_user, scenario__deleted_at__isnull=True).order_by('-pk'),
        lambda row: {'id': row.pk, 'scenario_id': row.scenario_id, 'scenario_name': row.scenario.name, 'message': row.message, 'created_at': row.created_at, 'read_at': row.read_at})


@api_endpoint(['PATCH'], section='scenarios')
def acknowledge_alert(request, pk):
    row = AnalysisAlert.objects.filter(pk=pk, scenario__owner=request.api_user).first()
    if not row:
        raise ApiProblem('not_found', 'Alert not found.', 404)
    row.read_at = timezone.now(); row.save(update_fields=['read_at'])
    return JsonResponse({'id': row.pk, 'read_at': row.read_at})


@api_endpoint(['GET'], section='demographics')
def quality(request):
    from .models import GeographyMapReference
    stats = Statistic.objects.filter(integration__owner=request.api_user)
    sources = list(stats.values('integration_id', 'integration__name').annotate(observations=Count('pk'), last_seen=Max('last_seen_at')))
    references = GeographyMapReference.objects.filter(geography__statistic__integration__owner=request.api_user).distinct()
    from .routing import metadata
    return JsonResponse({'sources': sources, 'missing_values': stats.filter(value__isnull=True).count(),
        'routing':metadata(),
        'unresolved_sales_records':Sale.objects.filter(owner=request.api_user,geography__isnull=True).count() if permitted(request.api_user,'sales:read') else None,
        'locations_with_area': references.filter(area_km2__isnull=False).count(),
        'locations_with_coordinates': references.filter(latitude__isnull=False).count(),
        'recent_runs': list(SyncRun.objects.filter(owner=request.api_user).order_by('-created_at').values('id','integration_id','status','created_at','finished_at','error_code')[:20]),
        'reference': 'Population, age and income: Census 2022. Last collection time does not make the census reference current.'})


@api_endpoint(['GET'], section='sales')
def opportunities(request, pk):
    require(request.api_user, 'scenarios:read', 'demographics:read', 'events:read')
    scenario = scenario_for(request, pk)
    event = owned_event(request.api_user, request.GET.get('event_id', scenario.filters.get('event_id', '')))
    result = map_result(request.api_user, scenario.filters)
    sales = Sale.objects.filter(owner=request.api_user, event=event)
    if request.GET.get('edition'):
        sales = sales.filter(edition=request.GET['edition'])
    by_code = {row['municipality_code']: row['tickets'] for row in sales.values('municipality_code').annotate(tickets=Sum('tickets'))}
    rows = []
    for point in result['results']:
        code = point['geography']['code'] if point['geography']['level'] == 'city' else point['geography']['parent_code']
        rows.append({'geography': point['geography'], 'cohort_lower': point['lower_bound'], 'cohort_upper': point['upper_bound'],
            'uploaded_tickets_in_municipality': by_code.get(code, 0),
            'evidence': 'uploaded_sales' if code in by_code else 'no_uploaded_sales_record'})
    rows.sort(key=lambda row: (row['uploaded_tickets_in_municipality'] > 0, -row['cohort_lower']))
    return JsonResponse({'event_id': event.pk, 'uploaded_records': sales.count(), 'results': rows,
        'limitations': 'Exploratory prioritization, not demand prediction. Ticket buyers are not age/income matched. Absent records do not establish zero sales. Districts share municipal sales totals and must not be summed.'})


@api_endpoint(['GET'], section='reports')
def compare(request):
    require(request.api_user, 'scenarios:read', 'demographics:read')
    raw = request.GET.get('snapshots', '').split(',')
    if not 2 <= len(raw) <= 5 or any(not value.isdigit() or len(value)>18 for value in raw) or len(set(raw)) != len(raw):
        raise ApiProblem('invalid_comparison', 'Choose 2–5 distinct snapshot identifiers.')
    rows = list(ScenarioSnapshot.objects.filter(pk__in=raw, scenario__owner=request.api_user, scenario__deleted_at__isnull=True).select_related('scenario'))
    if len(rows) != len(raw):
        raise ApiProblem('not_found', 'Snapshot not found.', 404)
    if any(row.filters.get('event_id') for row in rows):
        require(request.api_user, 'events:read')
    result = []
    for row in rows:
        points = row.result['results']
        complete = all(point['upper_bound'] is not None for point in points)
        area = sum(point['area_km2'] or 0 for point in points)
        lower = sum(point['lower_bound'] for point in points)
        result.append({'snapshot_id': row.pk, 'scenario': row.scenario.name, 'captured_at': row.created_at,
            'filters': row.filters, 'locations': len(points), 'cohort_lower': lower,
            'cohort_upper': sum(point['upper_bound'] for point in points) if complete else None,
            'cohort_density_lower': lower/area if area and all(point['area_km2'] for point in points) else None,
            'coverage': row.result['coverage']})
    return JsonResponse({'results': result, 'limitations': 'Each column is a separate scenario. Do not add overlapping scenarios. Compare filters, reference years and geography levels before interpreting differences. No demand or conversion forecast is inferred.'})
