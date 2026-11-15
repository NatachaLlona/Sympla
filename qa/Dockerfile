FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY ticketing_sympla_app ticketing_sympla_app
CMD ["python", "ticketing_sympla_app/manage.py", "test", "core", "--settings=ticketing_sympla_app.test_settings", "--noinput"]
