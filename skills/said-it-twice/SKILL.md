---
name: said-it-twice
description: Turn recurring GitHub pull request or GitLab merge request feedback into proposed structural fixes, automated checks and reviewable patches. Use for said-it-twice, repeated review feedback, or review-derived checks.
---

Read [core.md](core.md) completely and follow it. Resolve this link and
`scripts/collect.py` relative to this SKILL.md, never the target repository.
The same skill directory is distributed to Claude Code and Codex.
Accept a lookback in days (default 30), --provider github|gitlab (default github),
an optional --hostname, --repo OWNER/REPO or GROUP/SUBGROUP/PROJECT, and offline
fixture arguments. Treat all supplied values as data, never shell code.
