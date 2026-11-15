"""Owned disposable Docker integration test; never targets the configured user stack."""

import importlib.util
import json
import subprocess
from pathlib import Path
import time
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("launcher", ROOT / "start.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def main():
    qa_root = ROOT / ".qa-local"
    qa_root.mkdir(exist_ok=True)
    config = qa_root / "config.jsonc"
    config.write_text(
        json.dumps(
            {
                "database": {"name": "SimplaQA", "port": 25424},
                "api": {"port": 18010},
                "auth": {"token_ttl_seconds": 120},
                "docker": {"project_name": "sympla-startup-qa"},
            }
        ),
        encoding="utf-8",
    )
    args = ["--config", str(config), "--state-dir", str(qa_root / "state")]
    if not (qa_root / 'state' / 'state.json').exists():
        with patch('builtins.input', side_effect=['qa_runtime', 'qa-client']), patch.object(
                launcher.getpass, 'getpass', side_effect=['invalid', 'QaDatabase1!', 'QaDatabase1!',
                                                        'QaClientPass1!', 'QaClientPass1!', '']):
            result = launcher.main(args)
    else:
        with patch('builtins.input', return_value='qa-client'), patch.object(
                launcher.getpass, 'getpass', side_effect=['QaClientPass1!', 'QaClientPass1!']):
            result = launcher.main(args + ['--reset-api-client'])
    if result:
        return result

    def request(path, payload=None, token=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        req = Request(
            "http://127.0.0.1:18010" + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers=headers,
        )
        with urlopen(req, timeout=15) as response:
            return json.load(response)

    result = request(
        "/api/v1/token/",
        {
            "grant_type": "client_credentials",
            "client_id": "qa-client",
            "client_secret": "QaClientPass1!",
        },
    )
    token = result["access_token"]
    assert result["expires_in"] == 120
    existing = request("/api/v1/schedules/", token=token)["results"]
    schedule = (
        existing[0]
        if existing
        else request(
            "/api/v1/schedules/",
            {"time": "09:30", "timezone": "Europe/Lisbon", "active": False},
            token,
        )
    )
    try:
        request('/api/v1/sync/', {}, token)
        raise AssertionError('Missing Sympla credentials should be rejected before queuing')
    except HTTPError as exc:
        assert exc.code == 503
        assert json.load(exc)['error'] == 'upstream_configuration'
    # Scheduled/operator-created jobs still exercise the worker's safe configuration failure.
    code = "from django.db import transaction; from core.services import enqueue\nwith transaction.atomic():\n run=enqueue('qa-operator')\n print(run.pk)"
    identifier = subprocess.check_output(['docker', 'exec', 'sympla-startup-qa-api-1',
        'python', 'manage.py', 'shell', '-c', code], text=True).strip().splitlines()[-1]
    run = {'id': identifier}
    for _ in range(20):
        runs = request("/api/v1/sync-runs/", token=token)["results"]
        item = next(item for item in runs if item["id"] == run["id"])
        if item["status"] not in ["queued", "running"]:
            assert (
                item["status"] == "failed"
                and item["error_code"] == "upstream_configuration"
            )
            break
        time.sleep(1)
    else:
        raise AssertionError("Worker did not process the queued manual job")
    # Restart must not prompt, reissue client credentials, or discard database contents.
    with patch(
        "builtins.input", side_effect=AssertionError("Unexpected setup prompt")
    ), patch.object(
        launcher.getpass,
        "getpass",
        side_effect=AssertionError("Unexpected password prompt"),
    ):
        assert launcher.main(args) == 0
    assert any(
        item["id"] == schedule["id"]
        for item in request("/api/v1/schedules/", token=token)["results"]
    )
    assert (qa_root / "state" / "client_secret").read_text() == ""
    with patch("builtins.input", return_value=""), patch.object(
        launcher.getpass, "getpass", side_effect=["QaRotatedPass1!", "QaRotatedPass1!"]
    ):
        assert launcher.main(args + ["--reset-api-client"]) == 0
    try:
        request("/api/v1/events/", token=token)
        raise AssertionError("A token remained valid after client secret rotation")
    except HTTPError as exc:
        assert exc.code == 401
    assert (
        request(
            "/api/v1/token/",
            {
                "grant_type": "client_credentials",
                "client_id": "qa-client",
                "client_secret": "QaRotatedPass1!",
            },
        )["token_type"]
        == "Bearer"
    )
    import psycopg

    with psycopg.connect(
        host="127.0.0.1",
        port=25424,
        dbname="SimplaQA",
        user="qa_runtime",
        password="QaDatabase1!",
    ) as db:
        with db.cursor() as cursor:
            cursor.execute(
                "SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname=current_user"
            )
            assert cursor.fetchone() == (False, False, False)
            cursor.execute(
                "SELECT has_table_privilege(current_user, 'core_auditlog', 'UPDATE'), "
                "has_table_privilege(current_user, 'core_auditlog', 'TRUNCATE')"
            )
            assert cursor.fetchone() == (False, False)
    assert launcher.main(args + ["--stop"]) == 0
    print(
        "PASS: Docker bootstrap, token endpoint, schedule persistence, worker, restart, credential rotation and restricted runtime role."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
