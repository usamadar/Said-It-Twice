import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_plugin_marketplace_and_shared_core(self):
        manifest = json.loads((ROOT / '.claude-plugin/plugin.json').read_text())
        marketplace = json.loads((ROOT / '.claude-plugin/marketplace.json').read_text())
        self.assertEqual(manifest['name'], 'said-it-twice')
        self.assertEqual(marketplace['name'], 'said-it-twice')
        entry = marketplace['plugins'][0]
        self.assertEqual(entry['name'], manifest['name'])
        self.assertEqual(entry['version'], manifest['version'])
        self.assertEqual(entry['source'], './')
        for path in ['skills/said-it-twice/SKILL.md', 'commands/said-it-twice.md', 'codex/prompts/said-it-twice.md']:
            self.assertIn('core.md', (ROOT / path).read_text())
        self.assertEqual(len(list(ROOT.rglob('core.md'))), 1)

    def test_installer_copies_complete_skill_and_preserves_existing_install(self):
        with tempfile.TemporaryDirectory(prefix='codex home ') as tmp:
            env = dict(os.environ, CODEX_HOME=tmp)
            result = subprocess.run(['bash', str(ROOT / 'scripts/install-codex.sh'), '--with-prompt'], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('use $said-it-twice', result.stdout)
            installed = Path(tmp) / 'skills/said-it-twice'
            for path in (ROOT / 'skills/said-it-twice').rglob('*'):
                if path.is_file() and '__pycache__' not in path.parts:
                    relative = path.relative_to(ROOT / 'skills/said-it-twice')
                    self.assertEqual((installed / relative).read_bytes(), path.read_bytes())
            self.assertTrue((Path(tmp) / 'prompts/said-it-twice.md').is_file())
            (installed / 'core.md').write_text('human content')
            second = subprocess.run(['bash', str(ROOT / 'scripts/install-codex.sh')], env=env, capture_output=True)
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual((installed / 'core.md').read_text(), 'human content')

    def test_fixture_patch_applies_and_enforces_invariant(self):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(ROOT / 'fixtures/sample-repo', root, dirs_exist_ok=True, ignore=shutil.ignore_patterns('said-it-twice', '__pycache__'))
            subprocess.run(['git', 'init', '-q', tmp], check=True)
            proposal = ROOT / 'fixtures/expected-patches/001-retries.patch'
            subprocess.run(['git', 'apply', '--check', str(proposal)], cwd=root, check=True)
            subprocess.run(['git', 'apply', str(proposal)], cwd=root, check=True)
            result = subprocess.run(['python3', '-m', 'unittest', 'discover', '-v'], cwd=root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('test_rejects_negative_retry_count', result.stderr)


if __name__ == '__main__':
    unittest.main()
