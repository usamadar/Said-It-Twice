When asked to analyse repeated review feedback, use the installed `said-it-twice`
skill. Read its `core.md` before collecting evidence or proposing checks. It is
the shared workflow used by Claude Code and Codex. Reports and proposed patches
belong only in `./said-it-twice/`; never apply, commit or push them as part of
that workflow. Start with a 30-day window unless the user specifies otherwise.
Select `--provider gitlab` for GitLab merge requests, including an explicit
`--hostname` for self-managed instances; GitHub is the default provider.
