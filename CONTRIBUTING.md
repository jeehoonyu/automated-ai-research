# Contributing

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest -q
```

## The rules that are not negotiable

This project exists to refuse unsupported conclusions. A change that makes it easier to publish
something unsupported is a regression even if every test passes.

1. **A gate must be able to return the bad verdict.** "Not measurable" is a reason to withhold,
   never a reason to pass. If a check cannot run, it reports `not_evaluated`, which blocks.
2. **Never claim success you did not earn.** A command that cannot do its job exits non-zero.
   Partial processing is `partial`, not `ok`.
3. **Docs may not out-run code.** If you document a capability, wire it or mark it unenforced.
4. **Every check must be shown to fire.** Deleting any single check must break at least one
   assertion. A check that cannot fire reads as evidence of correctness without being any.
5. **Do not weaken a test to make it pass.** If a test fails, first establish whether the test or
   the code is wrong. Several defects in this codebase were found exactly this way.

`docs/lessons-carried-forward.md` records where these came from. Read it before changing a gate.

## Adding a validation check

1. Write it in `src/research/validation/validator.py` returning a `CheckResult`.
2. Return `not_evaluated` — never `passed` — when inputs are missing.
3. Register it in `CHECKS`.
4. Add a benchmark case in `benchmark/expected/cases.json` naming your check and its status.
5. Add a test that seeds the defect and asserts *your* check fires, not merely that publication
   was blocked.

## Adding a schema constraint

Schemas live in `schemas/v1/` and are authored by `tools/generate_schemas.py`. Put the spec rule
in `$comment` — validation surfaces the nearest enclosing comment, so an agent is told *why* the
constraint exists rather than only which leaf failed.

## Style

Type hints on public interfaces. Deterministic serialisation. Atomic writes. No hidden global
mutable state. No network access in core processing. No provider-specific agent code.

Comments should explain **why**, especially where the reason is a failure mode that is not
obvious from the code.
