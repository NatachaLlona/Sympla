> Registro histórico do protótipo importado. A implementação atual está descrita em README.md e VALIDATION.md.

# Análise técnica e de segurança — 15/11/2026

## Finalidade e escopo

Revisão estática do código local e esquema SQL. O repositório remoto continha apenas README e estava arquivado. Não foram consultados dados da conta Sympla nem registros do banco local.

O protótipo pode servir de base para sincronização, catálogo interno e relatórios. Hoje consulta a API com s_token, percorre páginas e retorna todos os eventos em JSON. Não persiste eventos ou cria versões, apesar da descrição no GitHub. Modelos e testes estão vazios. O SQL propõe versões, eventos, endereços, organizadores e categorias em PostgreSQL; o Django está configurado com SQLite.

## Segurança: prioridades

| Prioridade | Evidência | Recomendação |
| --- | --- | --- |
| Alta | core/views.py:update sem autenticação ou autorização | Exigir identidade e permissão; limitar campos e eventos privados conforme o público. Qualquer visitante pode disparar chamadas usando o token do servidor e receber os eventos retornados. |
| Alta | settings.py original com chave fixa e DEBUG=True | Gerar nova chave, usar variável de ambiente e desligar DEBUG em produção. A cópia remove a chave fixa; DEBUG continua pendente. |
| Alta | .env com configurações de API e banco; SQLite local | Não versionar. O Git os ignora. Trocar credenciais caso tenham sido expostas; presença local não comprova vazamento. |
| Alta | Endpoint sem restrição de método, frequência ou páginas; acumula tudo na memória | Limitar chamadas, concorrência, páginas e tempo total; mover sincronização para job em background. Se passar a gravar, exigir POST com proteção CSRF ou autenticação apropriada. |
| Média | Paginação confia na estrutura e valores externos | Validar JSON, tipos, page_size positivo e avanço; parar em páginas vazias/repetidas. Há risco de divisão por zero, erro 500 e loop prolongado. |
| Média | Retorna response.text e str(e) | Responder erros genéricos; registrar detalhes em logs protegidos e sem tokens. |
| Média | Host configurável e redirects seguidos com token | Validar origem HTTPS autorizada e bloquear redirects ou validar destino. Não foi demonstrado SSRF por visitante: não há URL pública de entrada. |
| Média | Sem configuração de produção ou manifesto original | Configurar hosts, HTTPS, cookies Secure, backups, logs e privilégio mínimo no banco; validar, fixar e auditar dependências. |

O ambiente original contém Django 5.2.4. Há correções de segurança posteriores. requirements.txt propõe Django 5.2.19 como mínimo, ainda sujeito a validação no ambiente-alvo.

Fontes oficiais:
- https://www.djangoproject.com/weblog/2026/nov/03/security-releases/
- https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/

## Evolução sugerida

1. Definir perfis, público dos eventos, campos expostos e retenção.
2. Implementar modelos e migrations PostgreSQL; sincronização transacional e idempotente.
3. Criar job com lock, retries limitados, backoff e métricas.
4. Servir consultas paginadas do banco e adicionar filtros.
5. Testar autenticação, paginação, falhas da API e atomicidade com API simulada; adicionar CI e auditoria de dependências.

No SQL, avaliar índice único parcial para apenas uma versão ativa, BIGINT para IDs externos, timestamps com timezone e índices de consulta. UNIQUE convencional permite duplicatas envolvendo NULL: revisar deduplicação de endereços. url.py está vazio; urls.py é o arquivo efetivamente utilizado.

## Limites

Não houve pentest, implantação ou auditoria de infraestrutura. Não se afirma que ocorreu exploração. Autenticação, limites de consumo e configuração de produção são recomendações pendentes, não funcionalidades entregues. Não foram usadas credenciais reais para testar a API.

## Verificações executadas

`manage.py check` passou; `manage.py test` encontrou zero testes; `check --deploy` retornou seis alertas (HSTS, redirecionamento HTTPS, cookies de sessão e CSRF seguros, DEBUG e ALLOWED_HOSTS). Executados com Python 3.15.0 e Django 6.1.3 disponíveis na máquina, não com a faixa 5.2 proposta em requirements.txt. Portanto não validam essa combinação de dependências. O diff passou na checagem de espaços e não inclui .env, SQLite ou bytecode.
