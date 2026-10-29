import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'skills/said-it-twice/scripts/collect.py'
spec = importlib.util.spec_from_file_location('collector', SCRIPT)
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


class CollectorTests(unittest.TestCase):
    def test_offline_cli_preserves_source_and_collects_nested_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'src').mkdir()
            (root / 'src/CLAUDE.md').write_text('Use the public boundary.')
            (root / 'AGENTS.md').write_text('Keep configuration validated.')
            (root / 'config.py').write_text('unchanged = True\n')
            (root / 'node_modules').mkdir()
            (root / 'node_modules/AGENTS.md').write_text('Ignore dependency notes.')
            (root / 'said-it-twice').mkdir()
            (root / 'said-it-twice/AGENTS.md').write_text('Ignore generated output notes.')
            with patch.object(collector, 'run', side_effect=AssertionError('Offline must not call gh')):
                self.assertEqual(collector.main(['--root', tmp, '--fixture', str(ROOT / 'fixtures/comments.json'),
                                                '--now', '2026-10-29T12:00:00Z']), 0)
            data = json.loads((root / 'said-it-twice/evidence.json').read_text())
            self.assertEqual(len(data['comments']), 9)
            self.assertEqual([n['path'] for n in data['notes']], ['AGENTS.md', 'src/CLAUDE.md'])
            self.assertEqual((root / 'config.py').read_text(), 'unchanged = True\n')
            self.assertEqual(data['mode'], 'fixture')

    def test_paginated_get_flattens_every_page(self):
        with patch.object(collector, 'run', return_value='[{"id":1}]\n [{"id":2}]') as mocked:
            self.assertEqual(collector.api('repos/a/b/pulls?per_page=100', Path('.')), [{'id':1}, {'id':2}])
            command = mocked.call_args.args[0]
            self.assertEqual(command[0:4], ['gh', 'api', '--method', 'GET'])
            self.assertIn('--paginate', command)
            self.assertNotIn('--slurp', command)

    def test_old_pr_new_review_and_deduplication(self):
        start = collector.instant('2026-10-01T00:00:00Z')
        end = collector.instant('2026-10-29T00:00:00Z')
        inline = {'id':1, 'body':'Guard the boundary', 'created_at':'2026-10-02T00:00:00Z',
                  'pull_request_url':'https://api.github.com/repos/a/b/pulls/9'}
        def response(endpoint, root):
            if '/pulls/comments?' in endpoint:
                self.assertIn('since=2026-10-01T00:00:00Z&', endpoint)
                return [inline, inline, dict(inline, id=3, created_at='2026-09-01T00:00:00Z')]
            if '/reviews?' in endpoint:
                self.assertIn('/pulls/9/', endpoint)
                return [{'id':4, 'body':'Add validation', 'submitted_at':'2026-10-03T00:00:00Z'},
                        {'id':5, 'body':'Pending', 'submitted_at':None},
                        {'id':6, 'body':'  ', 'submitted_at':'2026-10-03T00:00:00Z'}]
            return [{'number':9, 'created_at':'2020-01-01T00:00:00Z', 'updated_at':'2026-10-04T00:00:00Z'},
                    {'number':10, 'updated_at':'2026-09-01T00:00:00Z'}]
        with patch.object(collector, 'api', side_effect=response):
            records = collector.live('a/b', Path('.'), start, end)
        self.assertEqual([c['id'] for c in records], ['inline:1', 'review:4'])
        self.assertEqual(records[1]['url'], 'https://github.com/a/b/pull/9')

    def test_window_is_inclusive_and_normalised_to_utc(self):
        start = collector.instant('2026-10-01T00:00:00Z')
        end = collector.instant('2026-10-02T00:00:00Z')
        for date in ['2026-10-01T01:00:00+01:00', '2026-10-02T00:00:00Z']:
            self.assertIsNotNone(collector.normalise({'id':1, 'body':'x', 'created_at':date}, 'inline', 1, 'a/b', start, end))
        self.assertIsNone(collector.normalise({'id':1, 'body':'x', 'created_at':'2026-10-02T00:00:01Z'}, 'inline', 1, 'a/b', start, end))

    def test_rejects_output_links_and_existing_evidence(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            (root / 'said-it-twice').symlink_to(outside, target_is_directory=True)
            with self.assertRaises(collector.CollectionError):
                collector.write_evidence(root, {})
            (root / 'said-it-twice').unlink()
            (root / 'said-it-twice').mkdir()
            target = Path(outside) / 'victim'
            target.write_text('unchanged')
            (root / 'said-it-twice/evidence.json').symlink_to(target)
            with self.assertRaises(collector.CollectionError):
                collector.write_evidence(root, {})
            self.assertEqual(target.read_text(), 'unchanged')
            (root / 'said-it-twice/evidence.json').unlink()
            collector.write_evidence(root, {'first':True})
            with self.assertRaises(collector.CollectionError):
                collector.write_evidence(root, {'overwrite':True})
            self.assertEqual(json.loads((root / 'said-it-twice/evidence.json').read_text()), {'first':True})

    def test_auth_failure_produces_no_partial_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(collector, 'run', side_effect=collector.CollectionError('gh failed: not authenticated')):
                self.assertEqual(collector.main(['--root', tmp]), 1)
            self.assertFalse((Path(tmp) / 'said-it-twice/evidence.json').exists())

    def test_rejects_invalid_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(collector.main(['--root', tmp, '--days', '0']), 1)
            self.assertEqual(collector.main(['--root', tmp, '--repo', '../bad']), 1)
            self.assertEqual(collector.main(['--root', tmp, '--now', '2026-10-01T00:00:00Z']), 1)

    def test_gh_failure_is_reported(self):
        with patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', 'permission denied')):
            with self.assertRaisesRegex(collector.CollectionError, 'permission denied'):
                collector.run(['gh', 'api', 'repos/a/b/pulls'], Path('.'))


if __name__ == '__main__':
    unittest.main()
