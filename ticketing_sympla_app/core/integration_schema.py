"""Integration CRUD, relational event views and lineage API contracts."""
def extend(schema):
    from .openapi import obj, text, integer, ref, operation, paged, response, PAGINATION, DATETIME, NULL_DATETIME
    from .connectors import CONNECTORS
    schemas, paths = schema['components']['schemas'], schema['paths']
    schema['tags'].append({'name': 'Integrations'})
    uid = text(format='uuid')
    boolean = {'type': 'boolean'}
    fields = {'id': uid, 'name': text(maxLength=80), 'provider': text(enum=list(CONNECTORS)), 'active': boolean,
              'is_default': boolean, 'revision': integer(), 'created_at': DATETIME, 'updated_at': DATETIME}
    schemas['Integration'] = obj(fields)
    schemas['IntegrationInput'] = {**obj({key: fields[key] for key in ('name', 'provider', 'active', 'is_default')}, ['name', 'provider']), 'additionalProperties': False}
    schemas['IntegrationUpdate'] = {**obj({key: fields[key] for key in ('name', 'active', 'is_default')}), 'additionalProperties': False}
    schemas['IntegrationList'] = paged('Integration')
    schemas['IntegrationProviderList'] = obj({'results': {'type': 'array', 'items': obj({
        'code': text(), 'connector_version': text(), 'credential_scope': text(),
    })}})
    schemas['EventObservation'] = obj({
        'id': integer(), 'event_id': integer(), 'event_version': integer(), 'run_id': uid, 'integration_id': uid,
        'provider': text(), 'external_id': text(), 'source': text(), 'actor': text(), 'collected_at': DATETIME,
        'fingerprint': text(), 'transformation_version': text(), 'evidence_type': text(enum=['import', 'legacy_version']),
    })
    schemas['EventObservationList'] = paged('EventObservation')
    for name in ('ScheduleInput', 'Schedule', 'SyncRun', 'Event'):
        schemas[name]['properties']['integration_id'] = uid
    schemas['SyncRun']['properties'].update({'integration_revision': integer(), 'connector_version': text(), 'collected_at': NULL_DATETIME})
    event_fields = schemas['Event']['properties']
    event_fields.update({key: text() for key in ('name', 'reference_id', 'detail', 'start_date', 'end_date', 'url', 'image', 'provider')})
    event_fields.update({key: {**boolean, 'nullable': True} for key in ('published', 'cancelled', 'private_event')})
    event_fields.update({'first_seen_at': NULL_DATETIME, 'last_seen_at': NULL_DATETIME, 'last_run_id': text(format='uuid', nullable=True)})
    event_fields['address'] = {**obj({key: text() for key in ('name', 'address', 'address_alt', 'address_num', 'neighborhood', 'city', 'state', 'zip_code', 'country', 'lat', 'lon')}), 'nullable': True}
    event_fields['host'] = {**obj({'name': text(), 'description': text()}), 'nullable': True}
    event_fields['categories'] = {'type': 'array', 'items': obj({'kind': text(enum=['primary', 'secondary']), 'name': text()})}

    def route(path, method, name, summary, section, result=None, body=None, code='200'):
        parameters = list(PAGINATION) if method == 'get' and path.endswith('/') and '{' not in path else []
        if '{integration_id}' in path:
            parameters.append({'name': 'integration_id', 'in': 'path', 'required': True, 'schema': uid})
        if '{event_id}' in path:
            parameters.append({'name': 'event_id', 'in': 'path', 'required': True, 'schema': integer()})
        action = {'get': 'read', 'post': 'write', 'patch': 'edit', 'delete': 'delete'}[method]
        permission = f'{section}:{action}'
        item = operation(name, summary, section.title(), ref(result) if result else None,
                         body=ref(body) if body else None, code=code, parameters=parameters,
                         description=f'Requires {permission}. All records are scoped to the authenticated API account. Integration deletion preserves imported events and history.')
        item['x-required-permission'] = permission
        item['responses']['404'] = response('Record not found or not accessible.', ref('Error'))
        item['responses']['409'] = response('Duplicate record, inactive integration or configuration conflict.', ref('Error'))
        paths.setdefault(path, {})[method] = item

    route('/api/v1/integrations/', 'get', 'listIntegrations', 'List integrations', 'integrations', 'IntegrationList')
    route('/api/v1/integrations/', 'post', 'createIntegration', 'Create an integration', 'integrations', 'Integration', 'IntegrationInput', '201')
    route('/api/v1/integrations/{integration_id}/', 'get', 'getIntegration', 'Read an integration', 'integrations', 'Integration')
    route('/api/v1/integrations/{integration_id}/', 'patch', 'updateIntegration', 'Update an integration', 'integrations', 'Integration', 'IntegrationUpdate')
    route('/api/v1/integrations/{integration_id}/', 'delete', 'deleteIntegration', 'Delete an integration', 'integrations', code='204')
    route('/api/v1/integration-providers/', 'get', 'listIntegrationProviders', 'List registered integration connectors', 'integrations', 'IntegrationProviderList')
    route('/api/v1/events/{event_id}/', 'get', 'getEvent', 'Read a relational event', 'events', 'Event')
    route('/api/v1/events/{event_id}/observations/', 'get', 'listEventObservations', 'Read event import lineage', 'events', 'EventObservationList')
    paths['/api/v1/events/{event_id}/observations/']['get']['parameters'] += list(PAGINATION)
    paths['/api/v1/events/']['get']['parameters'] += [
        {'name': 'integration_id', 'in': 'query', 'schema': uid}, {'name': 'city', 'in': 'query', 'schema': text()},
    ]
    sync = paths['/api/v1/sync/']['post']
    sync['requestBody']['content']['application/json']['schema'] = {**obj({'integration_id': uid}), 'additionalProperties': False}
    sync['description'] += ' Optional integration_id selects an active owned integration; omission selects the default. The worker rechecks integration revision before committing.'
    schema['info']['version'] = '4.0.0'
    schema['info']['description'] += ' Relational event storage is fed by registered connectors. Import observations link events, immutable versions, integrations and synchronization runs. Source date strings retain their supplied timezone semantics.'
