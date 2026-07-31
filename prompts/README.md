# Prompts

Copy-paste prompts for driving this platform with an AI agent. They are plain Markdown so you can
paste them into any tool — Claude Code, Codex, Cursor, a chat window — or `cat` them into a CLI.

| Prompt | Give it to | When |
|---|---|---|
| [`run-research.md`](run-research.md) | your main agent | you have a corpus and a question, and want a run taken from empty workspace to report |
| [`independent-review.md`](independent-review.md) | **a fresh agent, in a new session** | the run reaches `independent_review`. This one is not optional and not interchangeable |
| [`audit-this-repo.md`](audit-this-repo.md) | an agent working on the repository | you changed the tool and want to know what you broke |
| [`extend-a-gate.md`](extend-a-gate.md) | an agent working on the repository | you want to add a validation check for your own domain |

For orienting an agent in the repository generally, use [`../AGENTS.md`](../AGENTS.md) instead —
these four are task prompts, not maps.

## Why `independent-review.md` is separate

Because independence is a property of the **context the reviewer was given**, not of the conclusion
it reached. If you paste it into the same session that did the synthesis, the reviewer has already
seen the primary agent's reasoning, its confidence, and its grading of each claim — and no amount of
instructing it to ignore that makes it independent.

`research validate` cannot see into your session. It records what you declare, and
`confirmed_independent` additionally requires an attested `ReviewContext` artifact that validation
scans for leaked material. That catches an accidental leak. It does not make a false declaration
impossible, and nothing here claims otherwise.

## A note on using these honestly

Every one of these prompts can be satisfied by an agent that fabricates. The platform's gates catch
citations that do not resolve, claims with no evidence, contradictions never sought, and reviews that
did not happen. They do not catch a well-formed lie, and they are not meant to — a hash is an
integrity check, not a signature.

What the gates buy you is that the lie has to be *deliberate and self-consistent*, rather than the
ordinary thing that happens when a plausible sentence goes unchecked.
