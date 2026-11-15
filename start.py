"""Standard-library-only entry point for the local Docker application stack."""

import argparse
import getpass
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "ticketing_sympla_app"))
from core.password_policy import PASSWORD_RULES, valid_password


class StartupError(Exception):
    pass


def read_jsonc(path):
    """Remove comments/trailing commas outside strings, preserving quoted URLs and secrets."""
    source = Path(path).read_text(encoding="utf-8-sig")
    output, index, quoted, escaped = [], 0, False, False
    while index < len(source):
        char = source[index]
        if quoted:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            index += 1
        elif char == '"':
            quoted = True
            output.append(char)
            index += 1
        elif source.startswith("//", index):
            end = source.find("\n", index)
            index = len(source) if end < 0 else end
        elif source.startswith("/*", index):
            end = source.find("*/", index + 2)
            if end < 0:
                raise StartupError("Invalid configuration: unclosed JSONC comment.")
            output.append(" ")
            index = end + 2
        else:
            output.append(char)
            index += 1
    source = "".join(output)
    output, quoted, escaped = [], False, False
    for index, char in enumerate(source):
        if (
            not quoted
            and char == ","
            and source[index + 1 :].lstrip().startswith(("}", "]"))
        ):
            continue
        output.append(char)
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
    try:
        return json.loads("".join(output))
    except json.JSONDecodeError:
        raise StartupError(
            "Invalid JSONC configuration. Check comments, quotes and commas."
        ) from None


def load_config(path):
    data = read_jsonc(path)
    try:
        if set(data) != {"database", "api", "auth", "docker"}:
            raise ValueError()
        if (
            set(data["database"]) != {"name", "port"}
            or set(data["api"]) != {"port"}
            or set(data["auth"]) != {"token_ttl_seconds"}
            or set(data["docker"]) != {"project_name"}
        ):
            raise ValueError()
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,62}", data["database"]["name"]):
            raise ValueError()
        if not re.fullmatch(r"[a-z][a-z0-9_-]{2,40}", data["docker"]["project_name"]):
            raise ValueError()
        for port in [data["database"]["port"], data["api"]["port"]]:
            if type(port) is not int or not 1024 <= port <= 65535:
                raise ValueError()
        if data["database"]["port"] == data["api"]["port"]:
            raise ValueError()
        ttl = data["auth"]["token_ttl_seconds"]
        if type(ttl) is not int or not 60 <= ttl <= 86400:
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise StartupError(
            "Invalid configuration. Use the config.jsonc structure; ports must be distinct "
            "integers from 1024 to 65535, and token lifetime must be 60 to 86400 seconds."
        ) from None
    return data


def ask_identifier(prompt, pattern, error, default=None):
    while True:
        value = input(prompt).strip() or default
        if value and re.fullmatch(pattern, value):
            return value
        print(error)


def ask_password(label):
    print(PASSWORD_RULES)
    while True:
        value = getpass.getpass(label + ": ")
        if not valid_password(value):
            print("Invalid password. " + PASSWORD_RULES)
            continue
        if getpass.getpass("Confirm " + label.lower() + ": ") != value:
            print("Passwords do not match. Please try again.")
            continue
        return value


def secure_directory(directory):
    directory.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        user = subprocess.check_output(["whoami"], text=True).strip()
        result = subprocess.run(
            [
                "icacls",
                str(directory),
                "/inheritance:r",
                "/grant:r",
                user + ":(OI)(CI)F",
                "SYSTEM:(OI)(CI)F",
            ],
            capture_output=True,
        )
        if result.returncode:
            raise StartupError(
                "Could not restrict the local credentials directory permissions."
            )
    else:
        directory.chmod(0o700)


def write_file(path, value):
    # The containing directory is private. Readable files allow the non-root container to read bind-mounted secrets.
    path.write_text(value, encoding="utf-8")
    if os.name != "nt":
        path.chmod(0o644)


def run(command, env=None, quiet=False):
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=quiet, text=True)
    if result.returncode:
        raise StartupError(
            "Command failed: "
            + " ".join(command[:4])
            + ". Check Docker Desktop and container logs."
        )


def compose_environment(config, state_dir, state):
    env = os.environ.copy()
    env.update(
        {
            "COMPOSE_PROJECT_NAME": config["docker"]["project_name"],
            "STATE_DIR": state_dir.as_posix(),
            "DB_NAME": config["database"]["name"],
            "DB_PORT": str(config["database"]["port"]),
            "DB_USER": state["database_user"],
            "API_PORT": str(config["api"]["port"]),
            "API_TOKEN_TTL_SECONDS": str(config["auth"]["token_ttl_seconds"]),
            "API_CLIENT_ID": state["client_id"],
            "ROTATE_INITIAL_CLIENT": (
                "true" if state.get("client_setup_pending") else "false"
            ),
        }
    )
    # Prevent Compose interpolation of secrets from a caller's environment.
    return env


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Start PostgreSQL, API and scheduler in Docker."
    )
    parser.add_argument("--config", type=Path, default=ROOT / "config.jsonc")
    parser.add_argument("--state-dir", type=Path, default=ROOT / ".local")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument(
        "--check",
        action="store_true",
        help="Validate configuration and Docker without changing data",
    )
    actions.add_argument(
        "--stop",
        action="store_true",
        help="Stop containers without deleting database volumes",
    )
    actions.add_argument(
        "--logs", action="store_true", help="Follow API and worker logs"
    )
    actions.add_argument(
        "--reset-api-client",
        action="store_true",
        help="Set a new client secret and revoke existing tokens",
    )
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        print('Configuration: ' + str(args.config.resolve()), flush=True)
        run(["docker", "info"], quiet=True)
        run(["docker", "compose", "version"], quiet=True)
        if args.check:
            print(
                f"Configuration valid. Database: {config['database']['name']}; PostgreSQL port: "
                f"{config['database']['port']}; API port: {config['api']['port']}."
            )
            print(
                "Docker is available. Run python start.py for first-time credential setup."
            )
            return 0
        state_dir = args.state_dir.resolve()
        state_path = state_dir / "state.json"
        state = (
            json.loads(state_path.read_text(encoding="utf-8"))
            if state_path.exists()
            else None
        )
        if state and (
            state["database_name"] != config["database"]["name"]
            or state["project_name"] != config["docker"]["project_name"]
        ):
            raise StartupError(
                "Database name/project changed after initialization. Existing data will not be "
                "renamed or deleted automatically. Restore the configuration or plan a data migration."
            )
        if not state and (args.stop or args.logs):
            raise StartupError(
                "The Docker stack has not been configured yet. Run python start.py first."
            )
        base = [
            "docker",
            "compose",
            "--project-name",
            config["docker"]["project_name"],
            "--file",
            str(ROOT / "compose.yaml"),
        ]
        if not state:
            print(
                "First-time setup. Credentials are separate for PostgreSQL and the API client."
            )
            username = ask_identifier(
                "Database username: ",
                r"[a-z][a-z0-9_]{2,62}",
                "Username must start with a lowercase letter and contain 3 to 63 lowercase letters, digits or underscores.",
            )
            while username in {"postgres", "sympla_admin"}:
                print("That database username is reserved.")
                username = ask_identifier(
                    "Database username: ",
                    r"[a-z][a-z0-9_]{2,62}",
                    "Invalid database username.",
                )
            password = ask_password("Database password")
            client_id = ask_identifier(
                "API client ID (API username): ",
                r"[A-Za-z0-9_.-]{3,100}",
                "Client ID must contain 3 to 100 letters, digits, dots, underscores or hyphens.",
            )
            client_secret = ask_password("API client secret (API password)")
            sympla_token = getpass.getpass(
                "Sympla API token (optional; press Enter to configure later): "
            ).strip()
            secure_directory(state_dir)
            for name, value in {
                "db_password": password,
                "db_admin_password": secrets.token_urlsafe(48),
                "django_secret": secrets.token_urlsafe(64),
                "client_secret": client_secret,
                "sympla_api_key": sympla_token,
            }.items():
                write_file(state_dir / name, value)
            state = {
                "database_name": config["database"]["name"],
                "database_user": username,
                "project_name": config["docker"]["project_name"],
                "client_id": client_id,
                "client_setup_pending": True,
            }
            write_file(state_path, json.dumps(state, indent=2))
        elif args.reset_api_client:
            client_id = ask_identifier(
                f"API client ID [{state['client_id']}]: ",
                r"[A-Za-z0-9_.-]{3,100}",
                "Invalid client ID.",
                default=state["client_id"],
            )
            client_secret = ask_password("API client secret (API password)")
            write_file(state_dir / "client_secret", client_secret)
            state.update(client_id=client_id, client_setup_pending=True)
            write_file(state_path, json.dumps(state, indent=2))
        env = compose_environment(config, state_dir, state)
        if args.stop:
            run(base + ["stop"], env)
            print("Containers stopped. Database volume and credentials were preserved.")
            return 0
        if args.logs:
            run(base + ["logs", "--follow", "api", "worker"], env)
            return 0
        print("Building the application and starting PostgreSQL...")
        run(base + ["build", "api"], env)
        run(base + ["up", "--detach", "--wait", "db"], env)
        run(base + ["run", "--rm", "--no-deps", "bootstrap"], env)
        # The API client secret is only needed to create/rotate its password hash.
        write_file(state_dir / "client_secret", "")
        state["client_setup_pending"] = False
        write_file(state_path, json.dumps(state, indent=2))
        run(base + ["up", "--detach", "--wait", "api", "worker"], env)
        print(f"Ready. Swagger: http://127.0.0.1:{config['api']['port']}/docs/")
        print(
            f"Client ID: {state['client_id']}. Use your client secret in Swagger Authorize."
        )
        print("The worker is running in Docker. You may close this terminal.")
        return 0
    except (StartupError, OSError, json.JSONDecodeError) as exc:
        print(
            "Startup failed: "
            + (
                str(exc)
                if isinstance(exc, StartupError)
                else "A required file or program is unavailable."
            ),
            file=sys.stderr,
        )
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nSetup cancelled. No database volumes were deleted.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
