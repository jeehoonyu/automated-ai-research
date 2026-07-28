# Current goal

`PROJECT_GOAL.md` is the specification. **This file is the working goal against it** — what is being
built now and what would count as having built it. It changes; the specification does not.

## The goal

> **Make the platform detect the one failure it is known to be blind to: an independent review that
> was not independent.**

### Why this and not something else

The Claude Code conformance run (`benchmark/expected/claude-code/`) produced one finding that is
worse than any bug it found:

> My first attempt at the independent-review packet included the line *"submitted with support
> classification: conflicting_evidence"*. That is `primary_confidence`, an explicitly excluded input.
> **Nothing in the CLI could have detected the leak.**

That is not a defect in a check. It is a hole where a check should be. Every other gate in this
system decides by inspecting something; `reviewer_independence_sufficient` decides by reading a
boolean the host wrote about itself. Both committed conformance runs declare:

```json
"review_independence": { "primary_rationale_excluded": true, "…": true,
                         "status": "confirmed_independent" }
```

Nothing on disk distinguishes that from the same JSON written by a host that pasted the primary
agent's grade into the reviewer's prompt. The strongest status in the system is the one with the
least evidence behind it — which is precisely the fail-open shape recorded in
`docs/lessons-carried-forward.md` §6b.

Fixing it is also the only substantial thing that is *not* blocked right now: gate 38.10 waits on
Codex credits (Aug 1), and CI waits on the account's Actions billing. Neither is a code problem.

## What counts as done

| | Requirement | Done when |
|---|---|---|
| **G1** | The host can put the reviewer's actual context on the record, hashed and immutable | `ReviewContext` artifact exists, validates, is content-addressed |
| **G2** | The CLI scans that context for material the packet excluded, derived from *this run's own artifacts* | `check_independence_attested` reports `passed` / `failed` / `not_evaluated` |
| **G3** | `confirmed_independent` is no longer free | An unattested `confirmed_independent` blocks; `procedurally_isolated` remains available without attestation |
| **G4** | It catches the *actual historical leak*, verbatim | A regression test containing the real leaked sentence fails the check |
| **G5** | The rule is applied to our own committed evidence, whatever that costs | The conformance README and release checklist state the resulting downgrade, and a test pins it |

### G5 is the point of G5

The two committed runs declare `confirmed_independent` and have no attested context, because
attestation did not exist when they ran. Under this goal they can no longer earn that status.

**They will be recorded as downgraded, not grandfathered.** A `workflow_version` exemption for
"runs made before the rule" is exactly how a gate becomes decorative, and this repository already
carries three write-ups of that pattern. The evidence for gate 38.6 (contradiction *discovered* by
search) and the blocked/published outcomes is unaffected — only the independence tier moves.

## What this deliberately does not claim

Attestation checks **what the host says it sent**. A host that sends a leaky context and then attests
a clean one defeats it completely, and no local artifact can prevent that.

The honest description of the improvement is narrow and worth stating precisely:

- **Before** — a leak was undetectable, and an honest host had no way to demonstrate it had not
  leaked.
- **After** — an *accidental* leak is caught mechanically, and a *deliberate* one requires the host
  to falsify a hashed record rather than merely omit one.

That is the difference between no evidence and falsifiable evidence. It is not the difference
between untrusted and trusted.

## Not in scope

- **Codex conformance** — blocked on account usage limits until 2026-08-01. Procedure is in
  `docs/release-checklist.md`. Not simulated.
- **CI execution** — the first run on this repository was cancelled by GitHub before any job
  started: *"recent account payments have failed or your spending limit needs to be increased"*.
  Private repositories bill Actions minutes. This is an account setting, not a code defect.

  Running the pipeline's steps locally instead was worth doing anyway: **`ruff check src tests` and
  `mypy --strict src/research` had never executed**, and between them reported 119 findings. Both
  are clean now, so the "CI configuration" box on the release checklist is no longer describing a
  pipeline that would have failed on its first green billing cycle. That is the same defect class
  this project keeps finding in itself — a checked box with no execution behind it — and it was
  sitting in our own checklist.
