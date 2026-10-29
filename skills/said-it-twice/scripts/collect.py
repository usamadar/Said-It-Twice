#!/usr/bin/env python3
"""Read-only GitHub/GitLab feedback collection. Writes only beneath said-it-twice/."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, unquote, urlsplit


class CollectionError(Exception):
    pass


def run(args, cwd):
    result = subprocess.run(args, cwd=cwd, text=True, encoding='utf-8', capture_output=True)
    if result.returncode:
        raise CollectionError(f"{args[0]} failed: {result.stderr.strip()}")
    return result.stdout


def array_pages(raw, provider):
    # Both CLIs emit consecutive JSON documents, one per page, without a wrapper.
    pages = []
    decoder = json.JSONDecoder()
    remaining = raw.strip()
    while remaining:
        page, offset = decoder.raw_decode(remaining)
        pages.append(page)
        remaining = remaining[offset:].lstrip()
    if not pages or any(not isinstance(p, list) for p in pages):
        raise CollectionError(f'Expected paginated {provider} array response')
    return [item for page in pages for item in page]


def api(endpoint, root):
    # Explicit GET: gh otherwise changes method when fields are supplied.
    raw = run(['gh', 'api', '--method', 'GET', '--hostname', 'github.com', '--paginate', endpoint], root)
    return array_pages(raw, 'GitHub')


def gitlab_api(endpoint, root, hostname):
    raw = run(['glab', 'api', '--method', 'GET', '--hostname', hostname, '--paginate', endpoint], root)
    return array_pages(raw, 'GitLab')


def validate_hostname(hostname):
    host, separator, port = hostname.partition(':')
    if (len(host) > 253 or not host or
            any(not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label)
                for label in host.split('.')) or
            (separator and (not port.isascii() or not port.isdigit() or not 1 <= int(port) <= 65535))):
        raise CollectionError('--hostname must be a DNS hostname, optionally followed by :PORT')
    return hostname.lower()


def validate_gitlab_repo(repo):
    parts = repo.split('/')
    if len(parts) < 2 or any(part in {'.', '..'} or not re.fullmatch(r'[A-Za-z0-9_.-]+', part) for part in parts):
        raise CollectionError('GitLab project must be NAMESPACE[/SUBGROUP]/PROJECT')
    return repo


def infer_gitlab_repo(root, hostname):
    origin = run(['git', 'remote', 'get-url', 'origin'], root).strip()
    selected_host = urlsplit(f'https://{hostname}')
    if '://' in origin:
        parsed = urlsplit(origin)
        if parsed.scheme not in {'https', 'http', 'ssh', 'git'} or parsed.query or parsed.fragment:
            raise CollectionError('Unsupported origin URL; supply --repo explicitly')
        origin_host, project = parsed.hostname, unquote(parsed.path).strip('/')
        if parsed.scheme in {'https', 'http'}:
            default_port = 443 if parsed.scheme == 'https' else 80
            if (parsed.port or default_port) != (selected_host.port or default_port):
                raise CollectionError('Origin port does not match --hostname; supply --repo explicitly')
    else:
        parsed = re.fullmatch(r'(?:[^/@:\s]+@)?([^/:\s]+):(.+)', origin)
        if not parsed:
            raise CollectionError('Cannot infer GitLab project from origin; supply --repo explicitly')
        origin_host, project = parsed.groups()
    if not origin_host or origin_host.lower() != selected_host.hostname:
        raise CollectionError('Origin host does not match --hostname; supply --repo explicitly')
    return validate_gitlab_repo(project.removesuffix('.git'))


def instant(value):
    value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if value.tzinfo is None:
        raise ValueError('Timestamps must include a timezone')
    return value.astimezone(timezone.utc)


def normalise(item, kind, number, repo, start, end):
    body = (item.get('body') or '').strip()
    stamp = item.get('submitted_at') if kind == 'review' else item.get('created_at')
    if not body or not stamp or not start <= instant(stamp) <= end:
        return None
    return {'id': f'{kind}:{item["id"]}', 'kind': kind, 'pr': number,
            'body': body, 'created_at': stamp,
            'url': item.get('html_url') or f'https://github.com/{repo}/pull/{number}',
            'path': item.get('path'), 'author': (item.get('user') or {}).get('login')}


def live(repo, root, start, end):
    comments = []
    prs = set()
    # Repository endpoint finds new comments on old PRs without search's 1,000-result cap.
    since = start.isoformat().replace('+00:00', 'Z')
    endpoint = f'repos/{repo}/pulls/comments?since={since}&per_page=100'
    for item in api(endpoint, root):
        number = int(item['pull_request_url'].rstrip('/').split('/')[-1])
        record = normalise(item, 'inline', number, repo, start, end)
        if record:
            comments.append(record)
    # Submitted review bodies require per-PR requests. Updated-desc allows an early stop.
    # paginate/slurp obtains all pages; filter locally for complete coverage.
    for pr in api(f'repos/{repo}/pulls?state=all&sort=updated&direction=desc&per_page=100', root):
        if instant(pr['updated_at']) >= start:
            prs.add(pr['number'])
    for number in sorted(prs):
        for item in api(f'repos/{repo}/pulls/{number}/reviews?per_page=100', root):
            record = normalise(item, 'review', number, repo, start, end)
            if record:
                comments.append(record)
    return list({c['id']: c for c in comments}.values())


def live_gitlab(repo, root, start, end, hostname):
    endpoint = f'projects/{quote(repo, safe="")}/merge_requests'
    comments = {}
    seen = set()
    # Notes can arrive before a throttled MR updated_at is refreshed. Inspect
    # every MR rather than silently losing recent feedback on older requests.
    for mr in gitlab_api(f'{endpoint}?scope=all&state=all&per_page=100', root, hostname):
        number = int(mr['iid'])
        if number in seen:
            continue
        seen.add(number)
        url = mr.get('web_url') or f'https://{hostname}/{repo}/-/merge_requests/{number}'
        for discussion in gitlab_api(f'{endpoint}/{number}/discussions?per_page=100', root, hostname):
            thread = discussion['notes']
            thread_position = next((note['position'] for note in thread if note.get('position')), {})
            inline = any(note.get('type') == 'DiffNote' or note.get('position') for note in thread)
            for note in thread:
                body = (note.get('body') or '').strip()
                stamp = note.get('created_at')
                if note.get('system') or not body or not stamp or not start <= instant(stamp) <= end:
                    continue
                position = note.get('position') or thread_position
                source_id = f'note:{note["id"]}'
                comments[source_id] = {
                    'id': source_id, 'kind': 'inline' if inline else 'comment',
                    'pr': number, 'body': body, 'created_at': stamp,
                    'url': f'{url}#note_{note["id"]}',
                    'path': position.get('new_path') or position.get('old_path'),
                    'author': (note.get('author') or {}).get('username'),
                }
    return list(comments.values())


def notes(root):
    def onerror(error):
        raise error

    result = []
    excluded = {'.git', 'node_modules', '.venv', 'venv', 'vendor', 'said-it-twice'}
    for directory, dirs, files in os.walk(root, followlinks=False, onerror=onerror):
        dirs[:] = sorted(d for d in dirs if d not in excluded and not (Path(directory) / d).is_symlink())
        for name in sorted(set(files) & {'AGENTS.md', 'CLAUDE.md'}):
            path = Path(directory) / name
            if path.is_symlink():
                continue
            result.append({'path': path.relative_to(root).as_posix(), 'body': path.read_text(encoding='utf-8')})
    return result


def write_evidence(root, payload):
    # Reject symlinks and non-directories at every output path component.
    folder = root / 'said-it-twice'
    if folder.is_symlink() or (folder.exists() and not folder.is_dir()):
        raise CollectionError('Unsafe said-it-twice output directory')
    folder.mkdir(exist_ok=True)
    target = folder / 'evidence.json'
    # Finish writing before publishing. A hard link atomically creates the final
    # name without overwriting existing evidence or following an output symlink.
    temporary = None
    try:
        content = (json.dumps(payload, indent=2, ensure_ascii=False) + '\n').encode('utf-8')
        with tempfile.NamedTemporaryFile(dir=folder, prefix='.evidence-', suffix='.tmp', delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, target)
    except FileExistsError as exc:
        raise CollectionError('evidence.json already exists; archive the previous run before retrying') from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--days', type=int, default=30)
    parser.add_argument('--provider', choices=['github', 'gitlab'], default='github')
    parser.add_argument('--hostname', help='GitLab server hostname (default gitlab.com); GitHub supports github.com only')
    parser.add_argument('--repo', help='OWNER/REPO or GitLab NAMESPACE[/SUBGROUP]/PROJECT; inferred when omitted')
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--fixture', type=Path, help='Offline JSON fixture; never calls gh or git')
    parser.add_argument('--now', help='ISO timestamp for reproducible fixtures')
    args = parser.parse_args(argv)
    try:
        if args.days < 1:
            raise CollectionError('--days must be positive')
        if args.now and not args.fixture:
            raise CollectionError('--now is only available with --fixture')
        root = args.root.resolve(strict=True)
        if not root.is_dir():
            raise CollectionError('--root must be a directory')
        end = instant(args.now) if args.now else datetime.now(timezone.utc)
        start = end - timedelta(days=args.days)
        if args.fixture:
            data = json.loads(args.fixture.read_text(encoding='utf-8'))
            provider = data.get('provider', args.provider)
            if provider not in {'github', 'gitlab'}:
                raise CollectionError('Fixture provider must be github or gitlab')
            hostname = validate_hostname(args.hostname or data.get('hostname') or f'{provider}.com')
            repo = data['repo']
            comments = [c for c in data['comments'] if start <= instant(c['created_at']) <= end]
            comments = list({c['id']: c for c in comments}.values())
        else:
            provider = args.provider
            hostname = validate_hostname(args.hostname or f'{provider}.com')
            if provider == 'gitlab':
                repo = validate_gitlab_repo(args.repo) if args.repo else infer_gitlab_repo(root, hostname)
                comments = live_gitlab(repo, root, start, end, hostname)
            else:
                if hostname != 'github.com':
                    raise CollectionError('GitHub collection supports github.com only')
                repo = args.repo or run(['gh', 'repo', 'view', '--json', 'nameWithOwner', '--jq', '.nameWithOwner'], root).strip()
                if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?/[A-Za-z0-9_.-]+', repo) or repo.split('/')[-1] in {'.', '..'}:
                    raise CollectionError('Repository must be OWNER/REPO')
                comments = live(repo, root, start, end)
        coverage = ('Inline comments and submitted review bodies; excludes conversation comments, deleted feedback and inaccessible data.'
                    if provider == 'github' else
                    'Published merge request discussion notes, including inline threads and replies; excludes system events, unpublished drafts, deleted feedback and inaccessible data.')
        payload = {'schema_version': 1, 'repo': repo, 'mode': 'fixture' if args.fixture else provider,
                   'provider': provider, 'hostname': hostname,
                   'window': {'since': start.isoformat(), 'until': end.isoformat(), 'days': args.days},
                   'coverage': coverage,
                   'comments': sorted(comments, key=lambda c: (c['created_at'], str(c['id']))),
                   'notes': notes(root)}
        target = write_evidence(root, payload)
        try:
            print(target)
        except UnicodeEncodeError:
            # A redirected legacy console encoding must not make a completed
            # collection appear to fail and prevent a subsequent retry.
            print(str(target).encode('ascii', errors='backslashreplace').decode('ascii'))
        return 0
    except (CollectionError, OSError, ValueError, KeyError, TypeError, OverflowError) as exc:
        print(f'said-it-twice: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
