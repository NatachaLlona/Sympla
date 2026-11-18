FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY start.py config.jsonc /app/
COPY ticketing_sympla_app ticketing_sympla_app
COPY qa/verify_event_migration.py qa/verify_event_migration.py
CMD ["python", "ticketing_sympla_app/manage.py", "test", "core", "--settings=ticketing_sympla_app.test_settings", "--noinput"]
