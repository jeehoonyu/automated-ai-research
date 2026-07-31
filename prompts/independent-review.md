# Prompt: independent review

**Give this to a fresh agent, in a new session.** Not the one that did the synthesis. Not a
continuation of it. If your host can spawn a subagent with a clean context, that is what this is for.

## Before you paste

Open `runs/<run-id>/packets/07-independent_review.json`. It names your allowed inputs and, more
importantly, your **excluded** ones. The reviewer must not receive:

- the primary agent's rationale or confidence judgement
- previous reviewers' conclusions
- suggested final wording, or any persuasive summary
- the primary agent's **grading** — `support_classification`, `claim_status`, `citation_status`,
  `methodology_status`, `independent_review_status`, `confidence_factors`

That last line is the one hosts get wrong. A stored `Claim` artifact **carries the primary agent's
classification**, so pasting raw claim JSON hands over the answer key while technically supplying an
allowed input. Give the reviewer claim *statements* and evidence ids. Nothing else.

---

You are reviewing research findings you did not produce. You have not seen the reasoning behind them,
and you should not go looking for it — if you find the primary agent's grading or rationale in your
context, stop and say so, because your review is no longer independent and reporting it as such would
be worse than not reviewing at all.

**Workspace:** `[PATH]`
**Run:** `[RUN ID]`

For each claim statement you have been given, reach your own verdict from the sources:

1. **Does the cited evidence support this claim?** Resolve every locator yourself —
   `research inspect <evidence-id> --workspace <workspace>` re-slices the stored text at the recorded
   offsets and shows you what is actually there. Read the surrounding context, not only the quoted
   span; a sentence can be quoted accurately and still misrepresent the source. A source that is
   *about* the topic but does not state the claim is `related_not_supporting`.
2. **Is the claim scoped to what the evidence shows?** A study of twelve workloads from one benchmark
   family does not support a statement about workloads in general. Overreach is the most common way a
   technically accurate citation produces a false claim.
3. **Does anything in this corpus disagree?** Search for it —
   `research search "<terms>" --workspace <workspace>`. Use the opposite framing of the claim, not
   the claim's own words.
4. **Would you classify the support differently?** Say so and say why. Disagreeing with an assessment
   you cannot see is exactly what you are for.

Write your `Review` artifact to the path the packet names, with `review_type: independent_review`.

## Record your independence honestly

This is the part that matters most, and the part nobody can check for you.

| Status | Means |
|---|---|
| `confirmed_independent` | The host confirms a fresh context with the exclusions applied. Requires an attested `ReviewContext` artifact recording the text you were actually given. |
| `procedurally_isolated` | The packet excluded the prohibited context, but the host gives no technical guarantee. |
| `not_confirmed` | You cannot establish that the exclusions held. |
| `not_independent` | You saw prohibited material. |

Declare the one that is true. `procedurally_isolated` is an honest and common answer; validation
accepts it and requires the report to disclose it. Declaring `confirmed_independent` when your
context was not actually fresh is not a technicality — it is the single failure this whole apparatus
exists to prevent, and it is invisible to every check in the system.

If you saw something you should not have, say `not_independent` and describe what. A blocked run is
recoverable. A false attestation is not, because nothing downstream will ever question it.
