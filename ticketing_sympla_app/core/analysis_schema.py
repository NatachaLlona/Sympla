"""Contracts for uploads and the analysis workspace."""
def extend(schema):
    from .openapi import obj, text, integer, ref, operation, PAGINATION
    for tag in ('Sales', 'Scenarios', 'Reports'):
        schema['tags'].append({'name': tag})
    result = {'type': 'object', 'additionalProperties': True}
    scenario = obj({'name': text(maxLength=120), 'filters': {'type': 'object'}, 'watch': {'type': 'boolean', 'default': False}}, required=['name','filters'])
    definitions = [
        ('/api/v1/sales/uploads/','get','listSalesUploads','List owned, hashed sales import batches','Sales','sales:read',None),
        ('/api/v1/sales/uploads/','post','uploadSalesCsv','Validate and import an owned sales CSV atomically','Sales','sales:write',None),
        ('/api/v1/sales/summary/','get','summarizeSales','Compare recorded origins and event editions','Sales','sales:read',None),
        ('/api/v1/analysis/scenarios/','get','listAnalysisScenarios','List saved scenarios','Scenarios','scenarios:read',None),
        ('/api/v1/analysis/scenarios/','post','createAnalysisScenario','Save filters and capture immutable source evidence','Scenarios','scenarios:write',scenario),
        ('/api/v1/analysis/scenarios/{pk}/','get','readAnalysisScenario','Read an owned scenario','Scenarios','scenarios:read',None),
        ('/api/v1/analysis/scenarios/{pk}/','patch','editAnalysisScenario','Revise filters, name or source watching','Scenarios','scenarios:edit',{'type':'object'}),
        ('/api/v1/analysis/scenarios/{pk}/','delete','archiveAnalysisScenario','Archive a scenario while preserving history','Scenarios','scenarios:delete',None),
        ('/api/v1/analysis/scenarios/{pk}/snapshots/','get','listScenarioSnapshots','List immutable scenario captures','Scenarios','scenarios:read',None),
        ('/api/v1/analysis/scenarios/{pk}/snapshots/','post','captureScenarioSnapshot','Capture current source evidence','Scenarios','scenarios:write',None),
        ('/api/v1/analysis/scenarios/{pk}/report/','get','exportScenarioReport','Download JSON or a standalone HTML report with a map','Reports','reports:read',None),
        ('/api/v1/analysis/scenarios/{pk}/opportunities/','get','rankScenarioOpportunities','Compare census cohorts against uploaded municipal sales','Sales','sales:read',None),
        ('/api/v1/analysis/compare/','get','compareScenarioSnapshots','Compare 2–5 scenario snapshots without combining overlaps','Reports','reports:read',None),
        ('/api/v1/analysis/notes/','get','listAnalysisNotes','List commercial annotations','Scenarios','scenarios:read',None),
        ('/api/v1/analysis/notes/','post','createAnalysisNote','Save a commercial annotation','Scenarios','scenarios:write',obj({'text':text(maxLength=2000),'scenario_id':integer(),'geography_id':integer()},required=['text'])),
        ('/api/v1/analysis/alerts/','get','listAnalysisAlerts','Read local source update alerts','Scenarios','scenarios:read',None),
        ('/api/v1/analysis/alerts/{pk}/','patch','acknowledgeAnalysisAlert','Mark a local alert read','Scenarios','scenarios:edit',None),
        ('/api/v1/analysis/quality/','get','inspectAnalysisQuality','Inspect missing values, source freshness and import status','Demographics','demographics:read',None),
    ]
    for path,method,name,summary,tag,permission,body in definitions:
        params=[]
        if '{pk}' in path:
            params.append({'name':'pk','in':'path','required':True,'schema':integer(minimum=1)})
        if method=='get' and ('{pk}' not in path or '/snapshots/' in path):
            params += list(PAGINATION)
        for key,shape in ([('event_id',integer()),('edition',text())] if '/sales/summary/' in path or 'opportunities' in path else
            [('snapshots',text(description='Comma-separated list of 2–5 distinct snapshot IDs.'))] if path.endswith('/compare/') else
            [('format',text(enum=['json','html'],default='json')),('snapshot_id',integer())] if path.endswith('/report/') else []):
            params.append({'name':key,'in':'query','schema':shape})
        endpoint=operation(name,summary,tag,result,parameters=params,body=body,
            description=f'Requires {permission}. All data is API-account scoped. Additional demographics:read/events:read permissions apply when demographic or event evidence is read. Sales CSV accepts only sale_id,sold_on,municipality_code,tickets,revenue (UTF-8, ISO dates, decimal-point BRL), maximum 5 MiB/10000 rows. Corrections append immutable versions; repeated identical batches are idempotent. Missing uploads/origins never establish zero sales. No joint age/income demand forecast is inferred.')
        endpoint['x-required-permission']=permission
        if name=='uploadSalesCsv':
            endpoint['requestBody']={'required':True,'content':{'multipart/form-data':{'schema':obj({'event_id':integer(),'edition':text(maxLength=80),'file':text(format='binary')},required=['event_id','edition','file'])}}}
        schema['paths'].setdefault(path,{})[method]=endpoint
    for name,shape in [('bbox',text(description='west,south,east,north; only visible coordinates are queried.')),('geography_code',text()),('venue_lat',{'type':'number'}),('venue_lon',{'type':'number'}),('max_travel_minutes',{'type':'number','minimum':0,'maximum':1440,'description':'Local OSRM car estimate from locality seats to the event/venue; requires a prepared regional graph. No live traffic. Unroutable locations are excluded with explicit unknown coverage.'})]:
        schema['paths']['/api/v1/demographics/map/']['get']['parameters'].append({'name':name,'in':'query','schema':shape})
    schema['info']['version']='6.0.0'
