# Claude Code conformance run

Artifacts from an actual run of the canonical workflow by **Claude Code** (`claude-opus-5`) against
the generated benchmark corpus. Two runs, both from the same workspace and index.

| Run | Question | Outcome |
|---|---|---|
| `run-a-conflicting-evidence` | *Does process-in-memory reduce off-chip data movement?* | **blocked** — 14 passed, 1 failed, 0 not_evaluated |
| `run-b-verified-fact` | *What evaluation scope did the primary study use?* | **published** — 15 passed, 0 failed, 0 not_evaluated |

Both reached every stage and produced schema-valid artifacts. **Zero `not_evaluated` checks in either
run** — every gate had the inputs it needed to actually decide.

## Run A — the honest answer was "the sources disagree"

The contradiction-review stage ran a *new* search specifically seeking disagreement
(`increased data movement replication opposite direction`) and surfaced `pim-replication.pdf`, which
reports a **12 percent increase** where the primary study reports a **41 percent reduction**.

The resulting claim asserts the disagreement rather than either figure, and is classified
`conflicting_evidence` with `contradiction_status: unresolved`. Validation blocked publication on
`contradictions_disclosed`, requiring human review. `research report` refused with exit 5; the draft
names the blocking gate in its first lines.

**This is the correct outcome.** The corpus contains a genuine unresolved contradiction, so no
honest run of this question can be report-eligible.

It also closes the discovery half of gate 38.6: the contradiction was *found by searching*, not
handed to the agent.

## Run B — a directly checkable fact, published

A claim about the primary study's own stated evaluation scope: twelve workloads, one benchmark
family, one hardware platform, one random seed, no independent replication. Every component maps
one-to-one onto the cited passage. Classified `verified`, published, exit 0.

## What the independent reviewer did

Both runs used a **genuinely fresh subagent context** for the independent review, given only the
allowed inputs. Working alone, the reviewer:

- reached `conflicting_evidence` in run A and `verified` in run B **without being told** the primary
  agent's classification — matching in both cases
- independently determined the effective independent source count was **two, not four**,
  deduplicating the byte-identical copy and the industry-brief republication. That is spec §24
  reasoning arrived at unprompted, from source metadata alone
- flagged that "independent" applied to the replication is an *inference*, not something the cited
  text states
- noted that run A's claim presents the two sides as evidentially symmetric while omitting the
  design asymmetry (one platform / one seed versus three platforms / ten seeds with a control)
- stated the correct rule for `verified` — that it "turns on direct checkability rather than source
  count" — which is precisely the rule the validator was getting wrong (see below)

## Two defects this run exposed

**1. A real bug in the validator.** `check_source_independence` required multiple independent sources
for `verified` as well as `strongly_supported`, and so refused a correctly-scoped single-source fact.
Spec §23.1 reserves `verified` for *directly checkable* facts, and its own examples — a stated
publication date, a reported sample size, a documented configuration value — have exactly one
authoritative source. Fixed, with regression tests in both directions.

**2. An independence violation by the primary agent — me.** My first attempt at the independent-review
packet included the line *"submitted with support classification: conflicting_evidence"*. That is
`primary_confidence`, an explicitly excluded input. I caught it myself, discarded that review, and
re-ran with a clean packet; only the clean run is recorded here.

That is worth stating plainly: **independence is self-declared, and the platform enforces the
consequences of the declaration, not its truthfulness.** Nothing in the CLI could have detected the
leak. A host that declares `confirmed_independent` while quietly leaking the primary's judgement
would pass every gate. The mitigation is the packet's explicit exclusion list — and it failed on its
first real use, by the author of the packet.

## Reproducing

```bash
python benchmark/build_corpus.py /tmp/corpus
research init /tmp/ws && research import /tmp/corpus --workspace /tmp/ws
research index --workspace /tmp/ws
research run --question "Does process-in-memory reduce off-chip data movement?" --workspace /tmp/ws
# work the packets, then:
research validate <run-id> --workspace /tmp/ws
research report   <run-id> --workspace /tmp/ws
```

Agent prose will differ between runs and between hosts. What must match is the structure: schema
validity, reference resolution, gate results, and the final verdicts above.

## What this still does not establish

**Codex has not been run.** Gate 38.10 requires *both* hosts. Half of it is now evidenced; the other
half is not, and `docs/release-checklist.md` records it as still open.
