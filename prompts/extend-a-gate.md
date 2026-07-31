# Prompt: add a validation check for your domain

For an agent working on **the repository**. Adding a gate is the main way a fork adapts this platform
to its own field — medicine, law, finance, safety engineering — and it is the change most likely to
go subtly wrong, because a gate that cannot fail looks identical to one that never fires.

---

You are adding a validation check to `automated-ai-research`. Read `AGENTS.md` and
`docs/validation-rules.md` first.

**The gate to add:** `[DESCRIBE THE CONDITION THAT MUST BLOCK PUBLICATION]`

## Before writing anything, answer these

1. **What artifact carries the fact you are checking?** If nothing does, you are adding a schema
   field, not a check — do that first, in `src/research/schemas/v1/`, and regenerate.
2. **What does the check say when the input is absent?** This is the whole decision. If your answer
   is `passed`, you have built a gate that reports a clean bill of health for a question nobody
   asked. The answer is `not_evaluated`, which blocks exactly as `failed` does.
3. **Is it deterministic?** A check may verify that something was *recorded* — "the methodology
   review assessed sample size" — but it cannot judge whether the assessment was any good. "Was this
   considered?" is answerable; "was it considered well?" is not, and a check that pretends otherwise
   is worse than none.
4. **Does it belong to a profile?** If it should apply to medicine but not to general research, it is
   a profile rule, not an unconditional gate. A profile may only name triggers the validator can
   actually fire — a key nothing reads is rejected at load time on purpose.

## Write it

In `src/research/validation/validator.py`:

```python
def check_your_condition(ctx: RunContext) -> CheckResult:
    """One line on what it establishes, then WHY it exists — what goes wrong without it."""
    name = "your_condition_established"          # snake_case; this id is public
    relevant = [c for c in ctx.claims if ...]
    if not relevant:
        return CheckResult(name, "not_applicable", "nothing for this to judge")
    if <the fact was never recorded>:
        return CheckResult(name, "not_evaluated", "say precisely what was not established")
    if <the fact is recorded and wrong>:
        return CheckResult(name, "failed", "...", offending_ids,
                           human_review=ctx.rules.forces_human_review("your_trigger"))
    return CheckResult(name, "passed", f"{len(relevant)} checked")
```

Then add it to the `CHECKS` list. A check not in that list runs never and blocks nothing.

Four statuses, and the distinction between the middle two is the point:

| | Means | Blocks |
|---|---|---|
| `passed` | checked, and it holds | no |
| `failed` | checked, and it does not hold | **yes** |
| `not_evaluated` | could not run — inputs missing, artifact unreadable | **yes** |
| `not_applicable` | this run genuinely has nothing to judge | no |

Do not reach for `not_applicable` to make a run pass. It means "there is nothing here of this kind",
never "I could not tell".

## Do not restate a vocabulary

If your check compares against schema values, ask for them:

```python
from ..artifacts.registry import schema_enum
allowed = schema_enum("Claim", "support_classification")
```

A hand-copied set silently drops values added later, and the dropped value lands in whichever branch
you did not think about. That has happened here more than once; `tests/unit/test_vocabularies.py`
exists because of it. If your check genuinely needs a *judgement* about a subset — which values
establish the property — write it out **with the reason beside it**, and add it to that test file so
a schema change fails loudly.

## Prove it can fail

In `tests/integration/test_validation.py`, build a run that violates the condition and assert the
check reports the blocking status and that `report_eligible` is `False`. Then the part that actually
matters:

**Delete your check from `CHECKS` and confirm the test goes red.** If it stays green, your test is
measuring something else. Put it back.

## Document it

Add a row to the table in `docs/validation-rules.md`. This is not optional bookkeeping: a test
asserts that every check id a real run emits appears in that file, because a gate nobody outside the
code knows about cannot be relied on by anyone.

If the condition is one of the ones spec §8.8 names, add a benchmark case in
`benchmark/expected/cases.json` naming your check and its expected status — asserting only
"publication was blocked" passes when the wrong gate fired.

## Then run everything

```bash
pytest -q && ruff check src tests benchmark tools && mypy --strict src/research
python tools/generate_schemas.py --check
```
