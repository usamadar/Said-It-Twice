# Said It Twice

Turn repeated code review feedback into proposed automated checks for Claude Code
and Codex. Collect evidence, rank recurring themes, and review patches before
changing your codebase. MIT licensed.

Works with GitHub pull requests (PRs) and GitLab merge requests (MRs).

## Install

Requires Python 3.10+, Git and a current Claude Code or Codex installation. Live
GitHub collection requires GitHub CLI (`gh`); live GitLab collection requires
[GitLab CLI (`glab`)](https://gitlab.com/gitlab-org/cli#installation). The chosen
CLI must already be authenticated with read access to the target repository.
No Python packages, model API keys or separate model service are required. The
host agent supplies semantic analysis.

Claude Code, one shell line:

```sh
claude plugin marketplace add usamadar/Said-It-Twice && claude plugin install said-it-twice@said-it-twice
```

Restart Claude Code after installation. The command file is named
`said-it-twice`; Claude Code namespaces plugin commands. In your target repo:

```text
/said-it-twice:said-it-twice --days 30
```

You can also ask Claude to use the Said It Twice skill. For local development,
start Claude with `claude --plugin-dir /absolute/path/to/Said-It-Twice`.

Codex, one shell line (run where `said-it-twice-plugin` does not already exist):

```sh
git clone https://github.com/usamadar/Said-It-Twice.git said-it-twice-plugin && bash said-it-twice-plugin/scripts/install-codex.sh
```

The installer copies the exact Claude skill folder into
`${CODEX_HOME:-~/.codex}/skills/said-it-twice`. It refuses to overwrite an
existing skill. Restart Codex, open your target repo and invoke:

```text
$said-it-twice analyse the last 30 days of review feedback
```

An optional [AGENTS.md snippet](codex/AGENTS.snippet.md) is provided for your own
instructions. The installer does not edit AGENTS.md. For Codex versions that
support custom prompts, run the installer with `--with-prompt` on first install;
then `/prompts:said-it-twice --days 30` is also available. Custom prompts are a
legacy interface and may be unavailable in newer versions; the skill is the
primary interface.

Both tools read [one core workflow](skills/said-it-twice/core.md). There is no
separate Codex copy to drift. Upgrades require archiving the old installed skill
and rerunning the installer from an updated checkout. Restart the host afterwards.

## What it does

1. Collects GitHub inline review comments and submitted review bodies using
   read-only, paginated `gh api` calls. For GitLab, it uses `glab api` to collect
   published MR discussion notes, including general comments, inline notes,
   replies and resolved threads. The default window is 30 days. Root and nested
   AGENTS.md / CLAUDE.md notes supply context.
2. Uses your agent to group feedback by the underlying mistake, with source IDs
   and links. A recurring theme must appear on at least two distinct PRs or MRs.
   Rank by distinct PRs/MRs, then independent comments. Notes never inflate the
   counts.
3. Inspects the code and prefers a type, API boundary or module change that
   prevents the mistake. Next comes a lint rule, test or continuous integration
   check. A short AGENTS.md rule is the fallback only when automation is infeasible.
4. Writes `said-it-twice/report.md`, collected `evidence.json` and proposed
   unified diffs under `said-it-twice/patches/`.

The plugin never applies patches, stages, commits, pushes or posts feedback. All
workflow writes stay under `./said-it-twice/`. Existing evidence is not
overwritten; archive the old run before starting another. Installation itself
writes the skill into your tool's configuration directory.

## A 30-second report example

This is fictional feedback from the bundled fixture, not a live repository:

| Theme | PRs in 30 days | Independent comments | Proposed check |
| --- | ---: | ---: | --- |
| Reject negative retries | 3 | 3 | Validate in the public configuration boundary; add a regression test |
| Use pathlib for filesystem paths | 2 | 2 | Inspect call sites, then propose a scoped lint rule |

> “Please reject negative retry counts before starting the worker.”
> [Example PR 14](https://github.com/example/said-it-twice-demo/pull/14#discussion_r2)
>
> Proposal: reject negative values in `retries()`, so callers cannot bypass
> validation. Patch: `said-it-twice/patches/001-retries.patch`.
> Runtime validation: pending human application.

See the [full example report](fixtures/expected-report.md) and
[ready-to-apply sample patch](fixtures/expected-patches/001-retries.patch).
Two HTTP timeout comments on the same PR are deliberately excluded from recurring
themes. Praise and acknowledgements are excluded as well.

## Try offline

Clone this repository, then open `fixtures/sample-repo` in either host and ask:

```text
Use Said It Twice with --fixture /absolute/path/to/Said-It-Twice/fixtures/comments.json --now 2026-10-29T12:00:00Z
```

Use an absolute fixture path. The fixed timestamp keeps the fake comments inside
the window regardless of today's date. No hosting authentication or requests are
needed. Reports must remain labelled as fixture data. The agent should find two
recurring themes; wording can vary. Missing filesystem code deliberately prevents
a speculative pathlib patch.

To try just the deterministic collector from the repository root:

```sh
python3 skills/said-it-twice/scripts/collect.py --root fixtures/sample-repo --fixture fixtures/comments.json --now 2026-10-29T12:00:00Z
```

This writes evidence only. Run the skill in a host agent to generate a new report
and patches; the collector is not a standalone semantic clustering engine.

## Collect live feedback

GitHub is the default provider. Invoke the skill or run:

```sh
python3 skills/said-it-twice/scripts/collect.py --root /path/to/target/repo --days 30 --repo OWNER/REPO
```

Omit `--repo` to infer the repository with `gh repo view`. GitHub collection uses
GitHub.com explicitly.

For GitLab.com, select the provider and supply the project path. Subgroups are
supported:

```sh
python3 skills/said-it-twice/scripts/collect.py --root /path/to/target/repo --days 30 --provider gitlab --repo GROUP/SUBGROUP/PROJECT
```

For a self-managed GitLab instance, also select its hostname:

```sh
python3 skills/said-it-twice/scripts/collect.py --root /path/to/target/repo --days 30 --provider gitlab --hostname gitlab.example.com --repo GROUP/PROJECT
```

The GitLab hostname defaults to `gitlab.com`. Omit `--repo` to infer the project
path from the target's `origin` remote; its host must match the selected hostname.
Authenticate `glab` for that host before collection. The plugin reuses the existing
session; token-based authentication needs `read_api` access and permission to read
the project. Keep credentials in the CLI's supported configuration or environment,
outside repository files and plugin arguments.

The same flags work through the host skill or command, for example:

```text
/said-it-twice:said-it-twice --provider gitlab --repo GROUP/PROJECT --days 30
```

Evidence records the provider and hostname. Its existing `pr` field holds the
PR number or MR number, so counts remain comparable across the shared workflow.
The collector fails without writing evidence if an API request fails. It does
not silently switch to fixture data or another provider.

## Review and apply

Inspect every patch, the supporting evidence and pending validation. The agent
checks patch applicability with `git apply --check` when possible, without
applying it. Files with existing uncommitted changes are excluded from proposals.

Once satisfied, a human can run these commands in the target repository:

```sh
git apply --check -- said-it-twice/patches/001-retries.patch
git apply -- said-it-twice/patches/001-retries.patch
```

Run the project's tests and wire new checks into the required workflow. A proposed
check cannot prevent recurrence until someone applies and enables it. This plugin
does not grant itself permission to apply patches even if asked during a run.

## Limitations

- Semantic clustering and proposed fixes depend on the host model and its context
  window. They are not deterministic and may miss or misclassify feedback. Count
  and source IDs make results auditable, not infallible.
- GitHub includes review bodies and inline comments, excluding general PR
  conversation comments. GitLab includes published MR discussion notes and
  replies, including resolved discussions, excluding system events and
  unpublished draft review notes. Both providers exclude deleted or inaccessible
  feedback and external trackers. GitHub pending reviews are excluded. An old
  comment edited during the window is excluded unless it was also created during
  the window.
- Collection uses full pagination without GitHub search's 1,000-result cap.
  GitHub lists all PRs and fetches reviews for PRs updated since the cutoff.
  GitLab lists all MRs and fetches their discussions, including old MRs, rather
  than relying on MR update timestamps to find recent notes. Large repositories
  can be slow and hit API rate limits. A failed request stops the run; there is no
  resumable cache or truncation disguised as complete evidence.
- Nested notes are collected except under .git, node_modules, .venv, venv, vendor
  and said-it-twice. Symlinked notes/directories are skipped. Other large or
  generated folders may need human inspection.
- The workflow does not run arbitrary project tests that could modify the source
  tree. Runtime validation is normally pending. Insufficient context can yield
  a precise proposal without a patch.
- The collector enforces its own output path, refuses symlinks and existing
  evidence. Other host-agent writes rely on the shared instructions and host
  permissions; this is not an operating-system sandbox. Concurrent malicious
  filesystem modification is outside the threat model.
- Reviews and local notes may contain private information or prompt injection.
  They are treated as evidence, not commands. Your host processes that content
  under its existing data settings. Review reports before sharing them.
- GitHub Enterprise Server is not supported by this version. Install and command
  support may change between host releases. Automated tests validate packaging,
  collection and installation; they do not certify every Claude Code or Codex
  release.

## Development

```sh
python3 -m unittest discover -s tests -v
bash -n scripts/install-codex.sh
```

Tests use temporary directories and fake API responses, with no credentials or
live hosting data. They cover GitHub and GitLab collection, pagination, old
PRs/MRs with recent feedback, UTC boundaries, count-preserving evidence, note
scope, failures, output symlinks, existing output, the Codex installer and the
sample patch. Continuous integration runs Python 3.10, 3.12 and 3.14. The sample
patch is applied only to a disposable test copy.

Please include reproduction steps for bugs, keep both hosts on the shared core,
and do not commit real review data. Contributions are welcome under the
[MIT licence](LICENSE).
