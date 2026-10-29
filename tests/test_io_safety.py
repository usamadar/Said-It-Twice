import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'skills/said-it-twice/scripts/collect.py'
spec = importlib.util.spec_from_file_location('collector_io', SCRIPT)
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


class CollectorIOSafetyTests(unittest.TestCase):
    def test_multilingual_fixture_and_notes_work_under_ascii_locale(self):
        with tempfile.TemporaryDirectory(prefix='said-it-twice-io-') as tmp:
            root = Path(tmp)
            note = 'Use pathlib for paths. 验证配置。\n'
            body = 'Please reject invalid retries. 😀'
            (root / 'AGENTS.md').write_text(note, encoding='utf-8')
            original_source = "unchanged = '🤝'\n".encode('utf-8')
            (root / 'config.py').write_bytes(original_source)
            fixture = root / 'fixture.json'
            fixture.write_text(json.dumps({
                'repo': 'example/unicode-demo',
                'comments': [{
                    'id': 'inline:1',
                    'kind': 'inline',
                    'pr': 1,
                    'body': body,
                    'created_at': '2026-10-15T12:00:00Z',
                    'url': 'https://github.com/example/unicode-demo/pull/1#discussion_r1',
                    'path': 'config.py',
                    'author': 'reviewer',
                }],
            }), encoding='ascii')
            child_env = dict(os.environ, LC_ALL='C', LANG='C', PYTHONUTF8='0',
                             PYTHONCOERCECLOCALE='0')
            result = subprocess.run([
                sys.executable, str(SCRIPT), '--root', str(root),
                '--fixture', str(fixture), '--now', '2026-10-29T12:00:00Z',
            ], cwd=ROOT, env=child_env, capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stderr)
            evidence = json.loads((root / 'said-it-twice/evidence.json').read_text(encoding='utf-8'))
            self.assertEqual(evidence['comments'][0]['body'], body)
            self.assertEqual(evidence['notes'], [{'path': 'AGENTS.md', 'body': note}])
            self.assertEqual((root / 'config.py').read_bytes(), original_source)

    def test_unicode_root_succeeds_when_stdout_only_supports_ascii(self):
        with tempfile.TemporaryDirectory(prefix='said-it-twice-io-') as tmp:
            root = Path(tmp) / '資料'
            root.mkdir()
            fixture = Path(tmp) / 'fixture.json'
            fixture.write_text(json.dumps({'repo': 'example/demo', 'comments': []}), encoding='ascii')
            child_env = dict(os.environ, PYTHONIOENCODING='ascii')
            result = subprocess.run([
                sys.executable, str(SCRIPT), '--root', str(root),
                '--fixture', str(fixture), '--now', '2026-10-29T12:00:00Z',
            ], cwd=ROOT, env=child_env, capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stderr)
            evidence = json.loads((root / 'said-it-twice/evidence.json').read_text(encoding='utf-8'))
            self.assertEqual(evidence['mode'], 'fixture')
            self.assertEqual(evidence['comments'], [])
            self.assertIn('evidence.json', result.stdout)

    def test_unreadable_notes_subtree_fails_without_publishing_evidence(self):
        with tempfile.TemporaryDirectory(prefix='said-it-twice-io-') as tmp:
            root = Path(tmp)
            protected = root / 'src'
            protected.mkdir()
            (protected / 'AGENTS.md').write_text('Validate the public boundary.\n', encoding='utf-8')
            fixture = root / 'fixture.json'
            fixture.write_text(json.dumps({'repo': 'example/demo', 'comments': []}), encoding='utf-8')
            real_scandir = collector.os.scandir

            def scan(path):
                if Path(path) == protected:
                    raise PermissionError('Notes subtree is not readable')
                return real_scandir(path)

            stderr = io.StringIO()
            with patch.object(collector.os, 'scandir', side_effect=scan), contextlib.redirect_stderr(stderr):
                result = collector.main([
                    '--root', str(root), '--fixture', str(fixture),
                    '--now', '2026-10-29T12:00:00Z',
                ])
            self.assertEqual(result, 1)
            self.assertTrue(stderr.getvalue(), 'The failed traversal must be reported.')
            self.assertFalse((root / 'said-it-twice/evidence.json').exists())
            self.assertEqual((protected / 'AGENTS.md').read_text(encoding='utf-8'),
                             'Validate the public boundary.\n')

    def test_failed_unicode_serialization_leaves_no_evidence_and_allows_retry(self):
        with tempfile.TemporaryDirectory(prefix='said-it-twice-io-') as tmp:
            root = Path(tmp)
            with self.assertRaises(UnicodeError):
                collector.write_evidence(root, {'body': '\ud800'})
            folder = root / 'said-it-twice'
            self.assertFalse((folder / 'evidence.json').exists())
            if folder.exists():
                self.assertEqual(list(folder.iterdir()), [])
            payload = {'body': 'Valid feedback 😀'}
            collector.write_evidence(root, payload)
            self.assertEqual(json.loads((folder / 'evidence.json').read_text(encoding='utf-8')), payload)


if __name__ == '__main__':
    unittest.main()
