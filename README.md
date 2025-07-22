# Sympla
Aplicação Django que integra dados da API Sympla, normaliza e versiona eventos em um banco PostgreSQL.

-A aplicação consome eventos da API Sympla, normaliza os dados relacionados a organizador, endereço e categoria, e armazena tudo em tabelas separadas no PostgreSQL para manter integridade e evitar duplicidade. 
-Cada evento é versionado: sempre que uma alteração é detectada (comparando todos os campos, incluindo valores nulos), uma nova versão do evento é criada no banco. Isso permite manter um histórico completo das mudanças.

- Python 3
- Django
- PostgreSQL
- API Sympla
