import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'skills/said-it-twice/scripts/collect.py'
spec = importlib.util.spec_from_file_location('gitlab_collector', SCRIPT)
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


class GitLabCollectorTests(unittest.TestCase):
    def test_paginated_api_decodes_adjacent_pages_and_selects_hostname(self):
        endpoint = 'projects/group%2Fsubgroup%2Fproject/merge_requests?scope=all&state=all&per_page=100'
        with patch.object(collector, 'run', return_value='[{"iid":1}][{"iid":2}]') as mocked:
            records = collector.gitlab_api(endpoint, Path('.'), 'gitlab.example.test')
        self.assertEqual(records, [{'iid': 1}, {'iid': 2}])
        self.assertEqual(mocked.call_args.args, (
            ['glab', 'api', '--method', 'GET', '--hostname', 'gitlab.example.test', '--paginate', endpoint],
            Path('.'),
        ))

    def test_paginated_api_rejects_non_array_responses(self):
        with patch.object(collector, 'run', return_value='[{"iid":1}]{"message":"error"}'):
            with self.assertRaises(collector.CollectionError):
                collector.gitlab_api('projects/group%2Fproject/merge_requests', Path('.'), 'gitlab.com')

    def test_old_merge_requests_keep_recent_discussions_replies_and_resolved_notes(self):
        start = collector.instant('2026-10-01T00:00:00Z')
        end = collector.instant('2026-10-29T00:00:00Z')
        merge_request = {
            'iid': 42,
            'updated_at': '2020-01-01T00:00:00Z',
            'web_url': 'https://gitlab.example.test/group/subgroup/project/-/merge_requests/42',
        }
        inline = {
            'id': 1, 'type': 'DiffNote', 'body': 'Guard the public boundary.',
            'created_at': '2026-10-01T01:00:00+01:00', 'system': False,
            'position': {'new_path': 'src/new.py', 'old_path': 'src/old.py'},
            'author': {'username': 'reviewer'}, 'resolved': True,
        }
        reply = {
            'id': 2, 'type': 'DiscussionNote', 'body': 'Also cover zero.',
            'created_at': '2026-10-02T00:00:00Z', 'system': False,
            'author': {'username': 'another-reviewer'},
        }
        general = {
            'id': 3, 'type': None, 'body': 'Add a regression test.',
            'created_at': '2026-10-29T00:00:00Z', 'system': False,
        }
        deleted_file = {
            'id': 4, 'type': 'DiffNote', 'body': 'Preserve the compatibility boundary.',
            'created_at': '2026-10-03T00:00:00Z', 'system': False,
            'position': {'new_path': None, 'old_path': 'src/deleted.py'},
        }
        discussions = [
            {'id': 'resolved-thread', 'notes': [inline, reply]},
            {'id': 'general-thread', 'notes': [general]},
            {'id': 'deleted-file-thread', 'notes': [deleted_file]},
            {'id': 'duplicate-page', 'notes': [dict(inline)]},
            {'id': 'excluded', 'notes': [
                dict(general, id=5, system=True),
                dict(general, id=6, body='  '),
                dict(general, id=7, created_at='2026-09-30T23:59:59Z'),
                dict(general, id=8, created_at='2026-10-29T00:00:01Z'),
            ]},
        ]

        def response(endpoint, root, hostname):
            self.assertEqual(hostname, 'gitlab.example.test')
            self.assertTrue(endpoint.startswith('projects/group%2Fsubgroup%2Fproject/'))
            if '/discussions?' in endpoint:
                self.assertIn('/merge_requests/42/discussions?', endpoint)
                return discussions
            self.assertIn('scope=all', endpoint)
            self.assertIn('state=all', endpoint)
            self.assertNotIn('updated_after', endpoint)
            return [merge_request, dict(merge_request)]

        with patch.object(collector, 'gitlab_api', side_effect=response) as mocked:
            records = collector.live_gitlab('group/subgroup/project', Path('.'), start, end, 'gitlab.example.test')
        by_id = {record['id']: record for record in records}
        self.assertEqual(set(by_id), {'note:1', 'note:2', 'note:3', 'note:4'})
        self.assertEqual(len(records), 4)
        self.assertEqual([record['pr'] for record in records], [42] * 4)
        self.assertEqual(by_id['note:1']['kind'], 'inline')
        self.assertEqual(by_id['note:1']['path'], 'src/new.py')
        self.assertEqual(by_id['note:1']['author'], 'reviewer')
        self.assertEqual(by_id['note:1']['url'], merge_request['web_url'] + '#note_1')
        self.assertEqual(by_id['note:2']['author'], 'another-reviewer')
        self.assertEqual(by_id['note:2']['kind'], 'inline')
        self.assertEqual(by_id['note:2']['path'], 'src/new.py')
        self.assertEqual(by_id['note:3']['kind'], 'comment')
        self.assertIsNone(by_id['note:3']['path'])
        self.assertEqual(by_id['note:4']['path'], 'src/deleted.py')
        self.assertEqual(sum('/discussions?' in call.args[0] for call in mocked.call_args_list), 1)

    def test_gitlab_cli_writes_provider_host_and_merge_request_identity(self):
        note = {
            'id': 'note:17', 'kind': 'inline', 'pr': 9,
            'body': 'Validate the public API.', 'created_at': '2026-10-20T00:00:00Z',
            'url': 'https://gitlab.example.test/group/subgroup/project/-/merge_requests/9#note_17',
            'path': 'config.py', 'author': 'reviewer',
        }
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(collector, 'live_gitlab', return_value=[note]) as mocked:
                result = collector.main([
                    '--root', tmp, '--provider', 'gitlab', '--hostname', 'gitlab.example.test',
                    '--repo', 'group/subgroup/project',
                ])
            self.assertEqual(result, 0)
            evidence = json.loads((Path(tmp) / 'said-it-twice/evidence.json').read_text())
            self.assertEqual(evidence['mode'], 'gitlab')
            self.assertEqual(evidence['provider'], 'gitlab')
            self.assertEqual(evidence['hostname'], 'gitlab.example.test')
            self.assertEqual(evidence['repo'], 'group/subgroup/project')
            self.assertEqual(evidence['comments'], [note])
            self.assertEqual(mocked.call_args.args[0:2], ('group/subgroup/project', Path(tmp)))
            self.assertEqual(mocked.call_args.args[-1], 'gitlab.example.test')

    def test_gitlab_cli_infers_project_and_defaults_to_gitlab_com(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(collector, 'infer_gitlab_repo', return_value='group/project') as infer:
                with patch.object(collector, 'live_gitlab', return_value=[]) as live:
                    self.assertEqual(collector.main(['--root', tmp, '--provider', 'gitlab']), 0)
            self.assertEqual(infer.call_args.args, (Path(tmp), 'gitlab.com'))
            self.assertEqual(live.call_args.args[0], 'group/project')
            self.assertEqual(live.call_args.args[-1], 'gitlab.com')

    def test_github_remains_the_default_provider(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(collector, 'run', return_value='owner/repository\n') as run:
                with patch.object(collector, 'live', return_value=[]) as github:
                    with patch.object(collector, 'live_gitlab', side_effect=AssertionError('Must use GitHub')):
                        self.assertEqual(collector.main(['--root', tmp]), 0)
            evidence = json.loads((Path(tmp) / 'said-it-twice/evidence.json').read_text())
            self.assertEqual(evidence['mode'], 'github')
            self.assertEqual(evidence['provider'], 'github')
            self.assertEqual(evidence['hostname'], 'github.com')
            self.assertEqual(github.call_args.args[0], 'owner/repository')
            self.assertEqual(run.call_args.args[0][0:3], ['gh', 'repo', 'view'])

    def test_gitlab_auth_failure_writes_no_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(collector, 'run', side_effect=collector.CollectionError('glab failed: not authenticated')):
                self.assertEqual(collector.main([
                    '--root', tmp, '--provider', 'gitlab', '--repo', 'group/project',
                ]), 1)
            self.assertFalse((Path(tmp) / 'said-it-twice/evidence.json').exists())

    def test_later_discussion_failure_discards_partial_collection(self):
        note = {'id': 1, 'body': 'Add validation.', 'created_at': '2026-10-20T00:00:00Z', 'system': False}
        responses = [
            [{'iid': 1}, {'iid': 2}],
            [{'id': 'first-thread', 'notes': [note]}],
            collector.CollectionError('glab failed: API rate limit'),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(collector, 'gitlab_api', side_effect=responses):
                self.assertEqual(collector.main([
                    '--root', tmp, '--provider', 'gitlab', '--repo', 'group/project',
                ]), 1)
            self.assertFalse((Path(tmp) / 'said-it-twice/evidence.json').exists())

    def test_remote_inference_handles_https_ssh_and_scp_subgroups(self):
        remotes = [
            'https://gitlab.example.test/group/subgroup/project.git\n',
            'ssh://git@gitlab.example.test/group/subgroup/project.git\n',
            'git@gitlab.example.test:group/subgroup/project.git\n',
        ]
        for remote in remotes:
            with self.subTest(remote=remote):
                with patch.object(collector, 'run', return_value=remote):
                    self.assertEqual(
                        collector.infer_gitlab_repo(Path('.'), 'gitlab.example.test'),
                        'group/subgroup/project',
                    )

    def test_remote_inference_rejects_another_host_and_local_paths(self):
        for remote in ['https://github.com/group/project.git', '/tmp/group/project.git']:
            with self.subTest(remote=remote):
                with patch.object(collector, 'run', return_value=remote):
                    with self.assertRaises(collector.CollectionError):
                        collector.infer_gitlab_repo(Path('.'), 'gitlab.com')

    def test_remote_inference_matches_web_ports_but_keeps_ssh_transport_separate(self):
        remotes = [
            'https://gitlab.example.test:8443/group/project.git',
            'ssh://git@gitlab.example.test:2222/group/project.git',
        ]
        for remote in remotes:
            with self.subTest(remote=remote):
                with patch.object(collector, 'run', return_value=remote):
                    self.assertEqual(collector.infer_gitlab_repo(Path('.'), 'gitlab.example.test:8443'), 'group/project')
        with patch.object(collector, 'run', return_value='https://gitlab.example.test:9443/group/project.git'):
            with self.assertRaises(collector.CollectionError):
                collector.infer_gitlab_repo(Path('.'), 'gitlab.example.test:8443')

    def test_gitlab_hostname_rejects_urls_userinfo_and_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            for hostname in ['https://gitlab.example.test', 'user@gitlab.example.test', 'gitlab.example.test/path']:
                with self.subTest(hostname=hostname):
                    with patch.object(collector, 'run', side_effect=AssertionError('Invalid hostname must not contact a CLI')):
                        self.assertEqual(collector.main([
                            '--root', tmp, '--provider', 'gitlab', '--hostname', hostname,
                            '--repo', 'group/project',
                        ]), 1)
            self.assertFalse((Path(tmp) / 'said-it-twice/evidence.json').exists())

    def test_github_hostname_rejects_unsupported_enterprise_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(collector, 'run', side_effect=AssertionError('Unsupported host must not contact a CLI')):
                self.assertEqual(collector.main([
                    '--root', tmp, '--provider', 'github', '--hostname', 'github.example.test',
                    '--repo', 'owner/repository',
                ]), 1)
            self.assertFalse((Path(tmp) / 'said-it-twice/evidence.json').exists())

    def test_gitlab_project_validation_rejects_traversal_and_url_components(self):
        for repo in ['project', '../project', 'group/../project', 'group//project', 'group/project?x=1', 'group%2Fproject', 'group/project#note']:
            with self.subTest(repo=repo):
                with self.assertRaises(collector.CollectionError):
                    collector.validate_gitlab_repo(repo)

    def test_gitlab_fixture_preserves_provider_metadata_without_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / 'fixture.json'
            fixture.write_text(json.dumps({
                'provider': 'gitlab', 'hostname': 'gitlab.example.test',
                'repo': 'group/subgroup/project', 'comments': [],
            }))
            with patch.object(collector, 'run', side_effect=AssertionError('Fixture must stay offline')):
                self.assertEqual(collector.main([
                    '--root', tmp, '--fixture', str(fixture), '--now', '2026-10-29T12:00:00Z',
                ]), 0)
            evidence = json.loads((Path(tmp) / 'said-it-twice/evidence.json').read_text())
            self.assertEqual(evidence['mode'], 'fixture')
            self.assertEqual(evidence['provider'], 'gitlab')
            self.assertEqual(evidence['hostname'], 'gitlab.example.test')


if __name__ == '__main__':
    unittest.main()
