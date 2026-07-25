# Lessons carried forward

This platform is a fresh codebase, but it is not designed from first principles alone. A predecessor
project (**DryRobin**, an experiment-running multi-agent discovery loop) was built, run, and then
audited. It produced real findings — and a set of failures that map almost one-to-one onto the rules
in `PROJECT_GOAL.md`. Those failures were discovered empirically, which is worth more than the same
rules asserted abstractly.

This document records what was learned and where each lesson is enforced here. It exists so the same
mistakes are not rediscovered a third time.

---

## 1. A gate that cannot return the bad verdict is not a gate

**What happened.** DryRobin's `finding_gate` skipped every bias check whose statistic was `NaN` — and
`NaN` is exactly what thin evidence produces. A tournament with a *single* verdict returned
`{"label": "finding", "reasons": []}`: the most confident possible verdict on the least possible
evidence. Worse, the one check that did run (strength gap > 0) was *anti*-correlated with evidence
quality, because a degenerate comparison separates completely and produces a large gap.

**The rule.** Not-measurable is a reason to withhold, never a reason to pass.

**Here.** `unable_to_determine` and `human_review_required` are first-class successful outcomes
(spec §23.3, §44). `Envelope.exit_code()` is a pure function of the envelope's contents, so a command
cannot report errors and still exit `0`. Validation must *fail* report eligibility on missing
reviews, unresolved locators, and insufficient independence — absence of a check is never a pass.

## 2. Counting reports instead of sources inflates apparent support

**What happened.** DryRobin's consensus counted finding-*reports* rather than trajectories. One
trajectory emitting the same finding three times out of five produced `support_frac 0.6, kept=true` —
manufactured consensus from a single run. Ten times against four dissenting trajectories produced
`support_frac 2.0` with the conflict flag *suppressed*.

**The rule.** The denominator and the numerator must count the same kind of thing, and that thing
must be an independent source.

**Here.** This is spec §24 (source independence) and it is why `evidence_id` is content-derived:
two agents extracting the identical passage from the identical document version produce the
*identical* id, so duplicate evidence collapses instead of double-counting. Multiple documents never
automatically count as multiple independent sources — `duplicate`, `republication`, `revision_of`,
`shares_primary_dataset` are tracked relationships, and unknown independence cannot be promoted.

## 3. An agent that both produces and judges is doing self-assessment, not verification

**What happened.** DryRobin's "blind Verifier" was handed `{url, quote}` and asked to report whether
the quote appeared at the source. The same agent fetched *and* judged, and applied an inconsistent
standard in practice: one citation passed on a character-level difference while another failed on a
synonym. Nothing deterministic ever saw the evidence. One cycle recorded `hallucination_rate: 1.0` —
zero of two citations resolved — beside a passing verdict.

**The rule.** The agent supplies what only reading can supply; deterministic code decides what it
means.

**Here.** This is the spec's central architectural split (§3, §8.8): the CLI verifies schemas,
hashes, references, locators, lifecycle, and gates; host agents assess semantic support through typed
review artifacts; the CLI enforces their decisions **but must not claim to independently understand
source meaning**. Citation review compares a paraphrase against exact stored source text, and the
matcher — not the agent — decides whether it matches.

Practical detail worth keeping: naive exact matching false-negatives constantly on real documents.
Normalize NFKC, fold curly quotes and dash variants, reject soft-404 bodies (a page that "loads" but
says *404 Not Found* is not resolved), and refuse quotes too short to be evidence of anything.

## 4. Docs drift ahead of code, and then seed the next cycle

**What happened.** DryRobin's `ledger.md` was append-only and explicitly seeded the next research
cycle. It asserted a determinism result no code had ever computed, a `τ²` statistic that was actually
a plain standard deviation, and a "permanent regression test" that no test asserted. These were not
cosmetic: they were *input* to the next round of reasoning.

**The rule.** A claim in a doc must be backed by code, explicitly marked unenforced, or formally
retracted. Nothing else.

**Here.** `AGENTS.md` and `CLAUDE.md` are deliberately thin stubs pointing at one canonical workflow,
so per-host drift has nowhere to start. Commands for unimplemented phases exit **non-zero** with a
`not_implemented` category naming the phase — a CLI that exits 0 for work it did not do is the same
defect class as a report claiming support it does not have, and this codebase is not entitled to that
mistake in its own tooling. `tests/unit/test_foundation.py` enforces it.

## 5. The system computed the refutation and did not notice

**What happened.** The sharpest one. A validation script computed, printed, and stored:

    wine          heterogeneity_ratio 2530.3     effect +0.262
    breast_cancer heterogeneity_ratio 215170.7   effect +0.036
    digits        heterogeneity_ratio 277.2      effect -0.0098
    hurts_on: []

…and then emitted a hardcoded narrative asserting that scaling "can HURT (digits)" — contradicted by
its own empty `hurts_on` list — explained by a mechanism ("the effect tracks heterogeneity") that its
own three numbers refute, since the ratio ordering and the effect ordering disagree. That conclusion
was written into the ledger as the corrected finding.

**The rule.** Prose must never assert more than the structured data beneath it supports.

**Here.** Spec §32: *"The report generator must not strengthen the language of a claim beyond its
validated classification."* This is mechanically checkable — compare the rendered narrative against
the computed classification and the evidence set — and it should be a report-gating check, not a
reviewer's good intentions. Reports render *from* validated JSON; Markdown is a derived view and
never becomes more authoritative than the artifacts beneath it (§3.3).

## 6. A benchmark's positive controls must be tested too

**What happened.** A doc-claim guard was written and reported "all claims backed". Three of its nine
checks were silently self-satisfied: every backing predicate names its search literal, so the literal
appeared in the guard's own source and the guard found *itself* as evidence. The green result was
partly false. It was caught only by injecting known regressions and watching them slip through.

**The rule.** Verify that each check *fires* on a known-bad input, not only that it stays quiet on
good ones. A check that cannot fire reads as evidence of correctness.

**Here.** Spec §36.3 requires a benchmark containing deliberately unsupported claims, seeded
contradictions, related-but-non-supporting citations, dependent sources, an image-only page, and
prompt-injection content. Every one of those is a positive control. The release gates (§38) are
written as things that must be *detected*, not merely as things that must not crash.

## 7. Immutable history needs a retraction mechanism, not an eraser

**What happened.** Correcting an append-only ledger required a way to supersede a claim without
rewriting it. Rewriting would have destroyed the record of what the system actually believed; leaving
it would have kept feeding a false premise forward.

**The rule.** Corrections produce new versions plus an explicit superseding relationship. Scope a
retraction so it covers the history above it without silently blanket-excusing everything added
later.

**Here.** Spec §3.4 and §31: amendments carry target artifact id *and hash*, changed fields, reason,
identity metadata, replacement artifact id and hash, and trigger revalidation of any published report
they touch. Historical artifacts are never silently overwritten.

---

## What did *not* carry over

DryRobin's actual machinery — Bradley-Terry ranking, trajectory consensus, experiment runners — is
irrelevant here. That system generated its own evidence by running code; this one extracts evidence
from documents it must never modify. Different data model, no shared code.

The transferable part was never the algorithms. It was the catalogue of ways a system can look
rigorous while being wrong.
