"""OpenAPI contract for the plain Django views; examples contain no credentials."""


def ref(name):
    return {'$ref': '#/components/schemas/' + name}


def obj(properties, required=()):
    result = {'type': 'object', 'properties': properties}
    if required:
        result['required'] = list(required)
    return result


def text(**kwargs):
    return {'type': 'string', **kwargs}


def integer(**kwargs):
    return {'type': 'integer', **kwargs}


def response(description, schema=None):
    result = {'description': description}
    if schema:
        result['content'] = {'application/json': {'schema': schema}}
    return result


def query(name, schema, description):
    return {'name': name, 'in': 'query', 'required': False, 'schema': schema, 'description': description}


def path_id(name):
    return {'name': name, 'in': 'path', 'required': True, 'schema': integer(minimum=1)}


PAGINATION = [query('page', integer(minimum=1, maximum=100000, default=1), 'Página de resultados.'),
              query('page_size', integer(minimum=1, maximum=100, default=50), 'Itens por página.')]


def operation(name, summary, tag, result, code='200', parameters=None, body=None, example=None, description=''):
    responses = {
        code: response('Sucesso', result),
        '401': response('Token ausente, inválido ou usuário revogado.', ref('Error')),
        '403': response('Usuário sem permissão de escrita.', ref('Error')),
        '405': response('Método não permitido.', ref('Error')),
        '500': response('Falha interna; alterações não confirmadas são revertidas.', ref('Error')),
    }
    if parameters or body is not None:
        responses['400'] = response('Parâmetros ou corpo inválidos.', ref('Error'))
    result = {'operationId': name, 'summary': summary, 'tags': [tag],
              'description': description, 'responses': responses}
    if parameters:
        result['parameters'] = parameters
    if body is not None:
        media = {'schema': body}
        if example is not None:
            media['example'] = example
        result['requestBody'] = {'required': True, 'content': {'application/json': media}}
        responses['413'] = response('Corpo maior que 4096 bytes.', ref('Error'))
    return result


def paged(name, include_page=True):
    properties = {'count': integer(minimum=0), 'results': {'type': 'array', 'items': ref(name)}}
    if include_page:
        properties.update({'page': integer(minimum=1), 'page_size': integer(minimum=1, maximum=100)})
    return obj(properties, properties.keys())


DATETIME = text(format='date-time')
NULL_DATETIME = text(format='date-time', nullable=True)
JSON_OBJECT = {'type': 'object', 'additionalProperties': True}
SCHEMAS = {
    'Error': obj({'error': text(), 'required': text()}, ['error']),
    'ScheduleInput': {**obj({'time': text(pattern=r'^(?:[01]\d|2[0-3]):[0-5]\d$', example='09:30'),
                            'timezone': text(maxLength=100, example='Europe/Lisbon',
                                             description='Fuso IANA obrigatório.'),
                            'active': {'type': 'boolean', 'default': True}}, ['time', 'timezone']),
                      'additionalProperties': False},
    'ScheduleState': {**obj({'active': {'type': 'boolean'}}, ['active']), 'additionalProperties': False},
    'Schedule': obj({'id': integer(), 'time': text(example='09:30'), 'timezone': text(),
                     'active': {'type': 'boolean'}, 'next_run_at': NULL_DATETIME,
                     'created_at': DATETIME, 'created_by': text()},
                    ['id', 'time', 'timezone', 'active', 'next_run_at', 'created_at', 'created_by']),
    'QueuedRun': obj({'id': text(format='uuid'), 'status': text(enum=['queued'])}, ['id', 'status']),
    'SyncRun': obj({'id': text(format='uuid'), 'source': text(enum=['manual', 'scheduled']),
                    'actor': text(), 'schedule_id': integer(nullable=True), 'scheduled_for': NULL_DATETIME,
                    'status': text(enum=['queued', 'running', 'success', 'failed', 'cancelled']),
                    'created_at': DATETIME, 'started_at': NULL_DATETIME, 'finished_at': NULL_DATETIME,
                    'error_code': text(), 'counts': JSON_OBJECT}),
    'Event': obj({'id': integer(), 'external_id': text(), 'version': integer(minimum=1),
                  'updated_at': DATETIME, 'data': JSON_OBJECT}),
    'EventVersion': obj({'id': integer(), 'version': integer(minimum=1), 'created_at': DATETIME,
                         'run_id': text(format='uuid'), 'data': JSON_OBJECT, 'differences': JSON_OBJECT}),
    'AuditLog': obj({'id': integer(), 'interaction_id': text(format='uuid'), 'created_at': DATETIME,
                     'actor': text(), 'action': text(), 'resource': text(), 'target_id': text(),
                     'differences': JSON_OBJECT, 'outcome': text()}),
    'RequestLog': obj({'id': integer(), 'interaction_id': text(format='uuid'), 'started_at': DATETIME,
                       'finished_at': DATETIME, 'actor': text(), 'method': text(), 'path': text(),
                       'http_status': integer(minimum=100, maximum=599)}),
}
for name in ['SyncRun', 'Event', 'EventVersion', 'AuditLog', 'RequestLog']:
    SCHEMAS[name + 'List'] = paged(name)
SCHEMAS['ScheduleList'] = paged('Schedule', include_page=False)

PATHS = {
    '/ping/': {'get': {'operationId': 'ping', 'summary': 'Verificar se o processo responde',
        'tags': ['Status'], 'security': [], 'responses': {'200': {'description': 'pong',
        'content': {'text/html': {'schema': text(), 'example': 'pong'}}}}}},
    '/api/v1/schedules/': {
        'get': operation('listSchedules', 'Consultar horários diários', 'Agendamentos', ref('ScheduleList'),
            parameters=PAGINATION + [query('active', {'type': 'boolean'},
                'true = ativos, false = inativos. Omita para consultar ambos.')]),
        'post': operation('createSchedule', 'Cadastrar horário diário', 'Agendamentos', ref('Schedule'),
            code='201', body=ref('ScheduleInput'),
            example={'time': '09:30', 'timezone': 'Europe/Lisbon', 'active': True},
            description='Requer usuário com escrita. Confirmado significa ativo. Máximo de 100 horários.')},
    '/api/v1/schedules/{schedule_id}/': {
        'patch': operation('setScheduleState', 'Ativar ou desativar horário', 'Agendamentos', ref('Schedule'),
            parameters=[path_id('schedule_id')], body=ref('ScheduleState'), example={'active': False},
            description='Requer escrita. Desativar cancela jobs pendentes; não interrompe jobs em execução.'),
        'delete': operation('deleteSchedule', 'Excluir horário ativo ou inativo', 'Agendamentos', None,
            code='204', parameters=[path_id('schedule_id')],
            description='Requer escrita. Exclusão lógica preserva a auditoria e cancela jobs pendentes.')},
    '/api/v1/sync/': {'post': operation('queueManualSync', 'Solicitar leitura manual da Sympla',
        'Sincronização', ref('QueuedRun'), code='202', body={'type': 'object', 'additionalProperties': False},
        example={}, description='Requer escrita e worker em execução. Entra na fila sem exigir agendamento. '
        'O retorno 202 confirma a entrada na fila; acompanhe o resultado em sync-runs.')},
    '/api/v1/sync-runs/': {'get': operation('listSyncRuns', 'Consultar execuções e seus resultados',
        'Sincronização', ref('SyncRunList'), parameters=PAGINATION)},
    '/api/v1/events/': {'get': operation('listEvents', 'Consultar eventos atuais na base', 'Eventos',
        ref('EventList'), parameters=PAGINATION)},
    '/api/v1/events/{event_id}/versions/': {'get': operation('listEventVersions',
        'Consultar versões e campos alterados', 'Eventos', ref('EventVersionList'),
        parameters=[path_id('event_id')] + PAGINATION,
        description='event_id é o ID local retornado por GET /api/v1/events/. Versões são imutáveis.')},
    '/api/v1/audit-logs/': {'get': operation('listAuditLogs', 'Consultar auditoria de alterações',
        'Auditoria', ref('AuditLogList'), parameters=PAGINATION + [query(name, text(), 'Filtro exato.')
        for name in ['resource', 'target_id', 'actor']])},
    '/api/v1/request-logs/': {'get': operation('listRequestLogs', 'Consultar histórico de acesso à API',
        'Auditoria', ref('RequestLogList'), parameters=PAGINATION,
        description='Não registra headers, tokens, corpos ou parâmetros de consulta.')},
}
PATHS['/api/v1/schedules/']['post']['responses']['409'] = response('Horário duplicado ou limite atingido.', ref('Error'))
PATHS['/api/v1/sync/']['post']['responses']['409'] = response('Já existe uma execução manual pendente.', ref('Error'))
for path in ['/api/v1/schedules/{schedule_id}/', '/api/v1/events/{event_id}/versions/']:
    for item in PATHS[path].values():
        item['responses']['404'] = response('Registro não encontrado.', ref('Error'))

SCHEMA = {
    'openapi': '3.0.3',
    'info': {'title': 'Sympla Integration API', 'version': '1.0.0',
        'description': 'Autenticação por Bearer token de usuário de API, sem JWT ou login por senha. '
        'Crie o usuário no servidor com `python manage.py api_user create integration --write`. '
        'Clique em Authorize e cole somente o token, sem o prefixo Bearer. '
        'O token da Sympla permanece no servidor e não deve ser informado aqui. '
        'Recarregar a página remove a autorização da interface. As operações Try it out alteram dados reais.'},
    'servers': [{'url': '/', 'description': 'Servidor atual'}],
    'security': [{'ApiBearer': []}],
    'components': {'securitySchemes': {'ApiBearer': {'type': 'http', 'scheme': 'bearer',
        'description': 'Token opaco do usuário de API. Cole apenas o token; Swagger adiciona Bearer.'}},
        'schemas': SCHEMAS},
    'paths': PATHS,
}
