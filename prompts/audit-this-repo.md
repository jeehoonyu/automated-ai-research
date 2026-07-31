# Prompt: audit a change to the tool

For an agent working on **the repository**, not on a research workspace. This is the prompt that
found most of the defects listed in `CHANGELOG.md`, including several the test suite was green over.

Run it after you change validation, reporting, extraction, or the UI. Run it with several agents in
parallel if you can, one per lens — they find different things.

---

You are auditing a change to `automated-ai-research`, a platform whose entire purpose is refusing to
publish research conclusions that are not supported. Read `AGENTS.md` first, then
`docs/validation-rules.md`.

Your job is not to check that the tests pass. They do. Your job is to find the thing the tests are
green *about* without having asked.

## The shape of defect to hunt

Every serious defect in this repository's history has had one shape: **something reported "no
problem" about a question it never asked.** Not a crash, not a wrong answer — a confident silence.

Real examples, all of which passed a full green suite:

- A validation check returned `passed, "none unresolved"` for claims whose contradiction status was
  `not_checked`. Nobody had looked, and the gate said fine.
- Validation loaded agent-written artifacts through a bare `json.load`. One hand-edited word in a
  citation review flipped a run to publishable, and no hash was ever compared.
- Recording `unknown` **cleared** an independence gate that recording *nothing* correctly blocked —
  so writing the truth down passed where writing nothing failed.
- `report_eligible` was a boolean bound to nothing. `research status` answered `False` for every run
  that had ever existed, including runs `research validate` had just called eligible.
- A UI template restated a schema enum from memory, blocked on a value the schema does not contain,
  and painted a claim that had never been independently reviewed green.
- A gate tested one of seven extraction statuses, so evidence declaring *itself* unreliable published
  without a human.

Notice what these share: the flattering answer was reachable, and nothing forced the unflattering one.

## Ask these four questions of the change

**Q1 — What does an unlisted value do?** For every set, tuple, dict of statuses, and inline
membership test the change touches: take a value it does *not* name. Does the code block, or does it
fall through to the acceptable branch? An unlisted value producing the strict outcome is correct.
Producing the reassuring one is a finding.

**Q2 — Does anything claim to have checked something it did not?** A check that returns `passed` when
its inputs were absent. A count computed over a different set than the one displayed. A docstring or
a comment asserting a property the code does not have. A test whose assertion would hold against the
broken code too.

**Q3 — Can two components disagree about the same run?** `research status`, `research validate`,
`research report` and `research ui` all answer "may this be published". Trace the change through all
four. They have disagreed before, in both directions.

**Q4 — Is any vocabulary written down twice?** The schemas in `src/research/schemas/v1/` are the
authority. A Python set that mirrors one is a copy that can drift, and it drifts toward whichever
branch the author did not think about. `schema_enum()` exists so it does not have to be copied.

## Rules for what you report

- Point at a file and a line, and state the concrete input that triggers it. "This could be
  clearer" is not a finding.
- **Verify by execution where you can.** Write a throwaway test, run it, delete it. Do not report
  behaviour you inferred from reading. Several confident readings in this repo's history were wrong.
- A deliberate omission with a comment explaining it is **not** a finding. There are several
  load-bearing ones — `INDEPENDENCE_ESTABLISHING` excludes `unknown` and `cites` on purpose, and says
  why at length. Read the comment before reporting the code.
- Fail-closed behaviour is not a finding even where coverage is incomplete. Say so and move on.
- **An empty findings list is a real answer.** Say what you checked and that it held. A reviewer who
  never disagrees is indistinguishable from one who is not looking, and so is one who always does.

## Then try to refute your own findings

For each one, argue the opposite case as hard as you can: the code does not say what you think, a
guard elsewhere already prevents it, the trigger would not actually work, a schema constraint
forbids the value on write, or a test already pins it. **Default to refuted when you are uncertain.**

Report what survives, and report what you refuted and why — the refutations are often the more
useful half, because they say which parts are load-bearing.

## Finally

If you fix something, prove the fix is guarded: re-introduce the defect, watch the named test go red,
and put it back. If your edit preserves the file's byte length and lands in the same second, Python
will reuse the cached `.pyc` and your mutation will silently do nothing — purge `__pycache__` on both
sides. That has produced a false result here before.
