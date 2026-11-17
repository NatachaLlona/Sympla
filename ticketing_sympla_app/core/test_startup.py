import importlib.util
from pathlib import Path
import tempfile
from unittest.mock import patch
from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("sympla_start", ROOT / "start.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class StartupTests(SimpleTestCase):
    def test_jsonc_comments_strings_and_trailing_commas(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.jsonc"
            path.write_text(
                '{/* comment */ "url":"https://example.test/a,}", // comment\n "list":[1,2,],}',
                encoding="utf-8",
            )
            self.assertEqual(
                launcher.read_jsonc(path),
                {"url": "https://example.test/a,}", "list": [1, 2]},
            )

    def test_default_database_and_ports(self):
        config = launcher.load_config(ROOT / "config.jsonc")
        self.assertEqual(config["database"], {"name": "Simpla", "port": 2424})
        self.assertEqual(config["api"]["port"], 8010)
        self.assertEqual(config['frontend']['port'], 8011)
        self.assertEqual(config['audience_map']['port'], 8012)

    def test_frontend_port_is_optional_for_legacy_configs_and_must_be_distinct(self):
        config = {'database': {'name': 'Simpla', 'port': 2424}, 'api': {'port': 8010},
                  'auth': {'token_ttl_seconds': 3600}, 'docker': {'project_name': 'sympla'}}
        with patch.object(launcher, 'read_jsonc', return_value=config):
            self.assertEqual(launcher.load_config('fixture')['frontend']['port'], 8011)
        config['frontend']['port'] = 8010
        with patch.object(launcher, 'read_jsonc', return_value=config), self.assertRaises(launcher.StartupError):
            launcher.load_config('fixture')

    def test_invalid_password_reprompts_in_english(self):
        with patch.object(
            launcher.getpass,
            "getpass",
            side_effect=["bad", "ValidPass1!", "ValidPass1!"],
        ), patch("builtins.print") as output:
            self.assertEqual(launcher.ask_password("Database password"), "ValidPass1!")
        messages = " ".join(str(call) for call in output.call_args_list)
        self.assertIn("Invalid password.", messages)
        self.assertIn("8 to 16 characters", messages)
        self.assertIn("uppercase", messages)

    def test_map_port_defaults_for_upgrades_and_rejects_conflicts(self):
        config = {'database': {'name': 'Simpla', 'port': 2424}, 'api': {'port': 8010},
                  'auth': {'token_ttl_seconds': 3600}, 'docker': {'project_name': 'sympla'}}
        with patch.object(launcher, 'read_jsonc', return_value=config):
            self.assertEqual(launcher.load_config('fixture')['audience_map']['port'], 8012)
        config['audience_map']['port'] = 8011
        with patch.object(launcher, 'read_jsonc', return_value=config), self.assertRaises(launcher.StartupError):
            launcher.load_config('fixture')
