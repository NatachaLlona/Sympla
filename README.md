# Sympla — protótipo Django

Consulta eventos da conta associada ao token Sympla e devolve JSON.

- `/ping/`: responde pong.
- `/update/`: consulta /events, percorre páginas e devolve os eventos.
- `/admin/`: administração padrão Django, sem modelos de eventos.

Não há venda de ingressos, pagamentos ou interface de usuário. Não há gravação ou versionamento de eventos. O Django usa SQLite. O SQL PostgreSQL é uma proposta ainda não integrada.

## Desenvolvimento

Use Python 3.13 e um ambiente virtual novo. Instale requirements.txt, copie ticketing_sympla_app/.env.example para .env na mesma pasta e configure uma DJANGO_SECRET_KEY aleatória e o token Sympla. Dentro de ticketing_sympla_app, execute `python manage.py migrate`, `python manage.py check` e `python manage.py runserver`.

As dependências são faixas iniciais, ainda sem lock validado. Confirme o host de exemplo com a conta/documentação Sympla. Não reutilize o ambiente virtual original, copiado de outra máquina.

## Estado

Não implantar em produção: DEBUG está ativo e /update/ não exige autenticação. Veja ANALISE.md.
A cópia remove a chave fixa do Django, exige DJANGO_SECRET_KEY no ambiente e remove o import não utilizado de psycopg2. .env, banco local e caches estão ignorados pelo Git. Os arquivos originais permanecem intactos.
