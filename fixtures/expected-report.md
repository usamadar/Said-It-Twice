# Said It Twice: offline example

Repository: example/said-it-twice-demo. **Fixture data, not real GitHub reviews.**
Window: 2026-09-29 12:00 UTC to 2026-10-29 12:00 UTC (30 days).
Coverage: 9 fake inline comments and review bodies plus AGENTS.md.
Ranked by distinct PRs, then independent comments. Recurrence needs 2 PRs.

| Rank | Theme | PRs | Comments | Confidence | Proposed check | Patch |
| --- | --- | ---: | ---: | --- | --- | --- |
| 1 | Reject negative retries | 3 | 3 | High | Validate in the configuration boundary | expected-patches/001-retries.patch |
| 2 | Use pathlib for filesystem paths | 2 | 2 | Medium | A scoped lint rule after inspecting actual filesystem call sites | Unavailable: this fixture contains no path-building code |

## Reject negative retries

Invariant: callers cannot obtain a negative retry count through `retries()`.

- “Validate the retry count at the configuration boundary; negative retries should fail.” [PR 11](https://github.com/example/said-it-twice-demo/pull/11#discussion_r1), inline:1.
- “Please reject negative retry counts before starting the worker.” [PR 14](https://github.com/example/said-it-twice-demo/pull/14#discussion_r2), inline:2.
- “The configuration API still accepts -1 retries. Reject it at the boundary.” [PR 18](https://github.com/example/said-it-twice-demo/pull/18#discussion_r3), review:3.

Supporting IDs: inline:1, inline:2, review:3. AGENTS.md already calls for boundary
validation. Add a guard inside config.py's public `retries` function and a focused
regression test. This uses the existing boundary and standard library. Cost is
one comparison per call; negative values will now raise ValueError. Confirm that
no caller relies on negative sentinel values. Runtime validation is pending until
a human applies the patch. No patch has been applied to this fixture.

## Use pathlib for filesystem paths

- “Use pathlib rather than string concatenation when building file paths.” [PR 21](https://github.com/example/said-it-twice-demo/pull/21#discussion_r4), inline:4.
- “Please build filesystem paths with pathlib, not string concatenation.” [PR 23](https://github.com/example/said-it-twice-demo/pull/23#discussion_r5), inline:5.

Supporting IDs: inline:4, inline:5. AGENTS.md specifies pathlib. The fixture has
no filesystem API to restructure. Inspect the real call sites and lint setup
before proposing a scoped rule, such as Ruff PTH rules if Ruff is already used.
A broad ban on string addition would produce false positives. No dependency or
patch is proposed without that context. A written rule would duplicate AGENTS.md.

## Other evidence

- inline:7 and inline:8 concern HTTP timeouts on PR 29 only. Two comments on one
  PR do not establish recurrence.
- Excluded review:6: acknowledgement of a fix. Excluded review:9: praise.
- Semantic classification may vary between hosts and models. Example URLs are
  fictional. Deleted feedback, PR conversation comments and review metadata are
  outside this fixture. Notes do not add occurrences.

Review the report before sharing. Enforcement starts only after a human reviews
and applies the proposed patches and enables the checks.
