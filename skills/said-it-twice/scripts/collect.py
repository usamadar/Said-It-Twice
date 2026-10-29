#!/usr/bin/env python3
"""Read-only GitHub review collection. Writes only beneath said-it-twice/."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone


class CollectionError(Exception):
    pass


def run(args, cwd):
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    if result.returncode:
        raise CollectionError(f"{args[0]} failed: {result.stderr.strip()}")
    return result.stdout


def api(endpoint, root):
    # Explicit GET: gh otherwise changes method when fields are supplied.
    raw = run(['gh', 'api', '--method', 'GET', '--hostname', 'github.com', '--paginate', endpoint], root)
    # gh emits consecutive JSON documents, one per page. Decode without requiring
    # the newer --slurp option, so distribution-packaged gh versions also work.
    pages = []
    decoder = json.JSONDecoder()
    remaining = raw.strip()
    while remaining:
        page, offset = decoder.raw_decode(remaining)
        pages.append(page)
        remaining = remaining[offset:].lstrip()
    if not isinstance(pages, list) or any(not isinstance(p, list) for p in pages):
        raise CollectionError('Expected paginated GitHub array response')
    return [item for page in pages for item in page]


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


def notes(root):
    result = []
    excluded = {'.git', 'node_modules', '.venv', 'venv', 'vendor', 'said-it-twice'}
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in excluded and not (Path(directory) / d).is_symlink())
        for name in sorted(set(files) & {'AGENTS.md', 'CLAUDE.md'}):
            path = Path(directory) / name
            if path.is_symlink():
                continue
            result.append({'path': path.relative_to(root).as_posix(), 'body': path.read_text()})
    return result


def write_evidence(root, payload):
    # Reject symlinks and non-directories at every output path component.
    folder = root / 'said-it-twice'
    if folder.is_symlink() or (folder.exists() and not folder.is_dir()):
        raise CollectionError('Unsafe said-it-twice output directory')
    folder.mkdir(exist_ok=True)
    target = folder / 'evidence.json'
    # Exclusive create prevents following links or silently overwriting earlier runs.
    try:
        with target.open('x') as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write('\n')
    except FileExistsError as exc:
        raise CollectionError('evidence.json already exists; archive the previous run before retrying') from exc
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--days', type=int, default=30)
    parser.add_argument('--repo', help='OWNER/REPO; otherwise inferred using gh repo view')
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
            data = json.loads(args.fixture.read_text())
            repo = data['repo']
            comments = [c for c in data['comments'] if start <= instant(c['created_at']) <= end]
            comments = list({c['id']: c for c in comments}.values())
        else:
            repo = args.repo or run(['gh', 'repo', 'view', '--json', 'nameWithOwner', '--jq', '.nameWithOwner'], root).strip()
            if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?/[A-Za-z0-9_.-]+', repo) or repo.split('/')[-1] in {'.', '..'}:
                raise CollectionError('Repository must be OWNER/REPO')
            comments = live(repo, root, start, end)
        payload = {'schema_version': 1, 'repo': repo, 'mode': 'fixture' if args.fixture else 'github',
                   'window': {'since': start.isoformat(), 'until': end.isoformat(), 'days': args.days},
                   'coverage': 'Inline comments and submitted review bodies; excludes conversation comments, deleted feedback and inaccessible data.',
                   'comments': sorted(comments, key=lambda c: (c['created_at'], str(c['id']))),
                   'notes': notes(root)}
        print(write_evidence(root, payload))
        return 0
    except (CollectionError, OSError, ValueError, KeyError, TypeError) as exc:
        print(f'said-it-twice: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
