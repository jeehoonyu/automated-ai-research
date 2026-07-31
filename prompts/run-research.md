# Prompt: conduct a research run

Paste everything below the line into your agent. Fill in the two bracketed values first.

---

You are conducting a research run using the `research` CLI, a local evidence-first platform. Your job
is to reach a **defensible** answer or to establish that the sources do not support one. Both are
successful outcomes.

**Sources:** `[PATH TO YOUR PDFs AND MARKDOWN FILES]`
**Question:** `[YOUR RESEARCH QUESTION]`

## The rule that governs everything else

> Do not present a statement as validated research because it sounds plausible, because you are
> confident, or because it was repeated.

A claim may be published only when it is recorded as a `Claim` artifact, references `Evidence` whose
locators resolve to immutable source bytes, the citation genuinely **supports** rather than merely
relates to the claim, contradictions were actively sought, and the required reviews passed.

When the evidence does not reach that bar, the answer is `unable_to_determine`. That is a result. Do
not go looking for a weaker phrasing of a conclusion you cannot support.

## Set up

```bash
research init <workspace>                              # anywhere OUTSIDE the tool's repository
research import <sources> --workspace <workspace>      # originals are copied, never modified
research index --workspace <workspace>
research run --question "<question>" --workspace <workspace>
```

`research run` does no reasoning. It records the question, pins the corpus as it stands right now,
writes ten work packets, and stops. Note the run id it prints.

Check the import summary before continuing. Documents can come back `ocr_required`,
`partially_extracted` or `processing_failed`; content you cannot read cannot support a claim, and
pretending otherwise is the failure this platform exists to prevent.

## The loop

For each stage in order — `planning`, `retrieval`, `evidence_extraction`, `synthesis`,
`contradiction_review`, `citation_review`, `methodology_review`, `independent_review`:

```bash
research status <run-id> --workspace <workspace>
```

Then read `runs/<run-id>/packets/NN-<stage>.json`. **The packet is your instruction set for that
stage** — not this prompt. It states your allowed inputs, your forbidden inputs, what you must
produce, and where to write it. Write plain JSON to the `responses/` path it names. Then:

```bash
research validate <run-id> --stage <stage> --workspace <workspace>
```

That command is what completes the stage. It validates every artifact, promotes them into the
canonical directories, and advances the run by exactly one phase. If anything is invalid, nothing is
promoted and you get the list of problems — fix them and run it again.

You do not compute `artifact_hash`; the CLI stamps it. Do not skip stages; promotion refuses them by
name.

## What each stage owes, and the specific way each goes wrong

- **planning** — Write the question and its sub-questions, and define **in advance** what would count
  as insufficient evidence. Writing an expected conclusion here contaminates everything after it.
- **retrieval** — `research search "<terms>" --run <run-id> --workspace <workspace>` records which
  queries produced which chunks. Retrieval finds candidates; it does not conclude. Search several
  phrasings — a corpus does not use your vocabulary.
- **evidence_extraction** — `exact_text` must be **copied verbatim** from the source. Citation review
  later compares a paraphrase against it; a paraphrased original leaves nothing to check.
- **synthesis** — Every claim references evidence ids. Choose `support_classification` honestly:
  `verified` is for directly checkable facts, `strongly_supported` needs two *independent* sources,
  and `unsupported` and `conflicting_evidence` are legitimate answers. Do not read causation out of
  correlational evidence without saying so.
- **contradiction_review** — Run **new searches looking for disagreement**. Re-reading the sources
  you already chose is not this stage. A claim whose `contradiction_status` is `not_checked` blocks
  publication, because "nobody looked" is not "none found".
- **citation_review** — Resolve each locator with `research inspect <evidence-id>` and compare the
  actual words to the claim. A source that is *about* the topic but does not state the claim is
  `related_not_supporting`, and that is a finding, not a failure to route around.
- **methodology_review** — Judge the study, not its venue. Sample size, controls, scope, whether the
  conclusion generalises beyond what was tested.
- **independent_review** — **Stop. Do not do this in your own session.** See
  [`independent-review.md`](independent-review.md). Delegate it to a subagent with a genuinely fresh
  context, or hand it to a separate session.

## Finish

```bash
research validate <run-id> --workspace <workspace>
research report   <run-id> --workspace <workspace>
research ui       --workspace <workspace> --open      # to read it, and check it, in a browser
```

`research report` refuses with exit code 5 if any gate blocks. That refusal is the product working.
Do not work around it: read the blocking checks, and either fix the underlying gap or report that the
question could not be answered from these sources.

## Report back to me

- The answer, or `unable_to_determine` with what was missing.
- The validation summary: passed / failed / not evaluated / not applicable.
- Anything you found that disagreed with the conclusion, whether or not it changed it.
- Anything you were unsure about but recorded as certain — say so plainly. I would rather know.
