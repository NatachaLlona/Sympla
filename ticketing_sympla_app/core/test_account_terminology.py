import ast
from pathlib import Path
from django.test import SimpleTestCase


class AccountTerminologyTests(SimpleTestCase):
    def test_application_identifiers_distinguish_api_accounts(self):
        root = Path(__file__).resolve().parent
        ambiguous = {'user', 'users', 'username', 'user_identifier', 'user_id'}
        violations = []
        for path in root.rglob('*.py'):
            if 'migrations' in path.parts:
                continue  # Historical schema identifiers are retained for upgrade compatibility.
            tree = ast.parse(path.read_text(encoding='utf-8-sig'))
            for node in ast.walk(tree):
                name = node.id if isinstance(node, ast.Name) else node.arg if isinstance(node, ast.arg) else None
                if name in ambiguous:
                    violations.append(f'{path.name}:{node.lineno}')
        self.assertEqual(violations, [])
