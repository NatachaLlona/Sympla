FROM python:3.13-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
COPY start.py config.jsonc /app/
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home --uid 10001 app
COPY ticketing_sympla_app /app/ticketing_sympla_app
WORKDIR /app/ticketing_sympla_app
USER app

FROM runtime AS api
CMD ["waitress-serve", "--listen=0.0.0.0:8000", "--threads=4", "ticketing_sympla_app.wsgi:application"]

FROM runtime AS integration-sympla
CMD ["python", "manage.py", "sync_worker", "--provider", "sympla"]

FROM runtime AS integration-ibge
CMD ["python", "manage.py", "sync_worker", "--provider", "ibge"]
