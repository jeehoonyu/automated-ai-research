# Current goal

`PROJECT_GOAL.md` is the specification. **This file is the working goal against it** — what is being
built now and what would count as having built it. It changes; the specification does not.

---

## Goal 2 — make the shipped thing be the thing the docs describe

> **Three interfaces this project documents were not implemented: the installed package, the
> research profiles, and half the exit codes. Implement them, and make the acceptance tests capable
> of failing.**

### How it was found

Not by reading. By installing the built wheel into a clean environment and running the pipeline:

```
research --version   OK
research init        OK
research import      schema file is missing: .../Lib/schemas/v1/chunk-set.schema.json
research index       same
```

`SCHEMA_ROOT` was `Path(__file__).resolve().parents[3] / "schemas"` — the *repository* root. That
resolves in a source checkout and in an editable install, so 299 tests were green while the wheel
shipped no schemas at all. Validation happens on write, so **every command past `init` failed.**

The CI job meant to catch this ran `--version`, `init`, and one `test -f`. Its coverage was exactly
equal to the working subset. It would have passed forever.

Pulling that thread found two more of the same shape.

### The three

| | Claimed | Actually |
|---|---|---|
| **Installed package** | release checklist: `[x] pip install from a built wheel verified in a clean environment (package data ships)` | no schemas in the wheel; unusable past `init` |
| **Research profiles** | README, checklist, `docs/validation-rules.md` → "triggers are listed in the active research profile" | **no code read a profile file.** One hard-coded set, `{"medicine", "finance"}`, was the entire feature |
| **Exit codes** | spec §34 defines `6 = HUMAN_REVIEW_REQUIRED`, "an expected workflow state that automation still needs to detect" | **unreachable.** `human_review_required` was only ever a warning; `import` with `failed 0` exited **4**, `SOURCE_PROCESSING_FAILURE` |

`medicine.yaml` had promised `prohibited_confidence: [verified]`, three methodology requirements and
seven human-review triggers since the day it was written. It delivered one independence bar that the
hard-coded set happened to agree with.

### What counts as done

| | Requirement | Done when |
|---|---|---|
| **G1** | An installed copy works | schemas and profiles live under `src/research/`, ship in the wheel, and the full pipeline runs from a clean install |
| **G2** | The acceptance test can fail | the CI wheel job drives import → index → search → run → validate and asserts the gating exit code; `tests/unit/test_packaging.py` catches the class without needing CI |
| **G3** | Profiles decide something | `risk`, `reviewer_independence`, `prohibited_confidence` and `human_review_triggers` are read from the file and applied |
| **G4** | A profile cannot promise what nothing does | every key is honoured or declared in `NOT_IMPLEMENTED` with its reason; anything else is a load error, and a trigger no check can fire is rejected |
| **G5** | Every declared exit code is reachable | `test_every_declared_exit_code_is_reachable` enumerates `ExitCode` and produces each one |

### The rule that keeps G3 fixed

A profile key must be **honoured** or **declared unimplemented, with the reason**. Loading rejects
anything else, so a future key that nothing reads fails loudly instead of quietly meaning nothing.
Four keys are currently declared unimplemented — `methodology_review`, `contradiction_review`,
`report_sections`, `advisory_human_review_triggers` — each with why.

An unimplemented key is not a lie as long as it says so. A key that silently does nothing is.

### What this deliberately does not claim

- **`methodology_review.require_*` still does nothing.** Judging study design means reading the
  source, which is the host agent's job. Making it real needs the methodology review to record a
  per-item assessment the validator can check for *presence* — a good next goal, not this one.
- **Routing human-review triggers through the profile makes loosening possible.** A profile that
  omits a trigger is choosing not to require review for it. Both shipped profiles list all six, and
  a test pins that, so nothing is loosened today.
- **CI still has not executed.** The wheel job is now capable of failing, but no run has proved it.
  Every step it contains was run by hand against a real install instead.

---

## Goal 1 — attested reviewer independence *(complete)*

> Make the platform detect the one failure it is known to be blind to: an independent review that was
> not independent.

`confirmed_independent` now requires a `ReviewContext` artifact recording the verbatim text the host
attests it gave the reviewer, which `check_independence_attested` scans for excluded material drawn
from the run's own artifacts. Both committed conformance runs were **downgraded rather than
grandfathered**.

It catches an accidental leak and makes a deliberate one require falsifying a hashed record. It does
not make independence verifiable: a host that sends a leaky context and attests a clean one still
passes. See `docs/validation-rules.md` and `benchmark/expected/claude-code/README.md`.

---

## Not in scope

- **Codex conformance (gate 38.10)** — blocked on account usage limits until 2026-08-01. Procedure
  is in `docs/release-checklist.md`. Not simulated.
- **CI execution** — GitHub cancels every job before it starts: *"recent account payments have
  failed or your spending limit needs to be increased"*. Private repositories bill Actions minutes.
  An account setting, not a code defect.
