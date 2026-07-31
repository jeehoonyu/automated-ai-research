# CLAUDE.md

Read **[`AGENTS.md`](AGENTS.md)** — the repository map, the workflow, the invariants that must not
break, and how to verify a change. It is the same file every other tool reads, deliberately: this
project has no host-specific rules, because two hosts with two sets of rules quietly become two
standards of evidence.

Nothing Claude-specific belongs here. If a rule is worth writing down, it is worth every agent
following it, so it goes in `AGENTS.md`.

One thing that *is* worth knowing here, because Claude Code can do it and most hosts cannot: the
`independent_review` stage requires a genuinely fresh context. Delegating it to a subagent with a
clean context is what makes `confirmed_independent` honest rather than aspirational. See
[`prompts/independent-review.md`](prompts/independent-review.md) — and note that pasting a stored
`Claim` artifact into that subagent hands over the answer key, because the artifact carries the
primary agent's own grading.
