"""Bounded HTTPS reads from fixed IBGE hosts; no caller-supplied URLs or redirects."""
import hashlib
import io
import json
import time
import zipfile
import csv
from urllib.parse import urlsplit
import requests
from ...sync_exception import SyncError

MAX_BYTES = 16 * 1024 * 1024
MAX_EXPANDED = 64 * 1024 * 1024


def download(url):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.netloc not in ('ftp.ibge.gov.br', 'servicodados.ibge.gov.br') or parsed.fragment:
        raise SyncError('ibge_configuration')
    deadline = time.monotonic() + 90
    try:
        with requests.Session() as session:
            session.trust_env = False
            with session.get(url, timeout=(5, 25), stream=True, allow_redirects=False) as response:
                if response.status_code != 200:
                    raise SyncError('ibge_http_error', http_status=response.status_code)
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > MAX_BYTES or time.monotonic() > deadline:
                        raise SyncError('ibge_response_limit')
                    chunks.append(chunk)
                content = b''.join(chunks)
                return content, hashlib.sha256(content).hexdigest()
    except requests.RequestException:
        raise SyncError('ibge_connection_error') from None


def csv_rows(content):
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = archive.infolist()
            files = [item for item in members if item.filename.lower().endswith('.csv')]
            if len(files) != 1 or sum(item.file_size for item in members) > MAX_EXPANDED:
                raise SyncError('ibge_response_limit')
            raw = archive.read(files[0])
        # Official aggregate CSVs are Windows-1252; UTF-8 products are also accepted.
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = raw.decode('cp1252')
        reader = csv.DictReader(io.StringIO(text), delimiter=';')
        if not reader.fieldnames or len(reader.fieldnames) > 500:
            raise SyncError('ibge_invalid_response')
        for index, row in enumerate(reader):
            if index > 100000 or None in row:
                raise SyncError('ibge_response_limit')
            yield {key.upper(): value for key, value in row.items()}
    except (zipfile.BadZipFile, UnicodeError, csv.Error, RuntimeError, OSError):
        raise SyncError('ibge_invalid_response') from None


def json_document(content):
    try:
        return json.loads(content)
    except (ValueError, UnicodeError):
        raise SyncError('ibge_invalid_response') from None
