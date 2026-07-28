"""The leak scanner (GOAL.md G1–G4).

The first test is the reason this module exists: the sentence in it is the ACTUAL text that leaked
into an independent-review packet during the Claude Code conformance run, quoted from
`benchmark/expected/claude-code/README.md`. Nothing in the CLI could detect it at the time. If this
test ever passes vacuously — because the rule was loosened, or the sentence was tidied up — the
capability is gone and the docs will still claim it.

The negative tests matter as much. A check that fires on legitimate context gets switched off, and a
switched-off check is worse than no check because the documentation goes on listing it. So the false
-positive guards are pinned too, and so are the gaps the scanner is documented as NOT closing.
"""

from __future__ import annotations

from research.runs.lifecycle import Stage
from research.runs.packets import GRADING_FIELDS, build_packet
from research.validation.independence import NGRAM, scan_context

# Verbatim, from the conformance run's own write-up of its independence violation.
THE_REAL_LEAK = "submitted with support classification: conflicting_evidence"


def _rules(leaks):
    return {leak.rule for leak in leaks}


# --------------------------------------------------------------- it catches the real one


def test_the_actual_historical_leak_is_detected():
    """The sentence that got past every gate in the conformance run."""
    context = (
        "You are reviewing a claim about process-in-memory. Here is the claim, "
        f"{THE_REAL_LEAK}. Assess whether the cited passage supports it."
    )
    leaks = scan_context(context)
    assert "graded_classification_disclosed" in _rules(leaks)
    assert "conflicting_evidence" in leaks[0].excerpt


def test_raw_claim_json_handed_to_the_reviewer_is_a_leak():
    """The ambiguity that made the old contract defeatable.

    `claims` was an allowed input while `primary_confidence` was excluded — and a Claim artifact
    carries `support_classification`. Pasting the stored artifact satisfied the allow-list and
    defeated the exclusion in the same act.
    """
    context = '{"claim": "PIM reduces data movement", "support_classification": "verified"}'
    assert _rules(scan_context(context)) >= {"graded_classification_disclosed",
                                             "excluded_field_present"}


def test_every_grading_field_is_detected_in_key_position():
    for name in GRADING_FIELDS:
        context = f'{{"claim": "x", "{name}": "something"}}'
        assert "excluded_field_present" in _rules(scan_context(context)), name


def test_a_prior_review_conclusion_reaching_the_independent_reviewer_is_detected():
    conclusion = ("the cited passage describes a simulated workload rather than the hardware "
                  "measurement the claim asserts")
    assert len(conclusion.split()) > NGRAM, "the fixture must be long enough to be detectable"
    prior = [{"review_type": "citation_review", "review_id": "REV-1", "findings": [conclusion]}]
    leaks = scan_context(f"Background for your review: {conclusion}. Now assess the claim.",
                         reviews=prior)
    assert "prior_review_conclusion_present" in _rules(leaks)


def test_a_context_whose_hash_of_shapes_is_clean_reports_nothing():
    context = ("Question: does process-in-memory reduce off-chip data movement? "
               "Claim under review: the primary study reports a 41 percent reduction. "
               "Evidence: 'we observe a 41% reduction in off-chip traffic' (p. 4). "
               "Assess whether the evidence supports the claim.")
    assert scan_context(context) == []


# --------------------------------------------------------------- it does not fire on the contract


def test_the_work_packet_itself_is_not_flagged():
    """The packet LISTS the forbidden names. Flagging the contract that forbids the leak would fire
    on every honest host that includes it, which is how a check gets disabled."""
    packet = build_packet(run_id="RUN-x", stage=Stage.INDEPENDENT_REVIEW, question="q",
                          profile="default", workspace_root="/ws")
    import json
    assert scan_context(json.dumps(packet, indent=2)) == []


def test_a_rendered_contract_explaining_each_exclusion_is_not_flagged():
    context = ("Excluded inputs for this stage:\n"
               "  - primary_rationale: the primary agent's reasoning\n"
               "  - primary_confidence: how confident the primary agent was\n"
               "Do not request or accept any of the above.")
    assert scan_context(context) == []


def test_evidence_prose_containing_the_word_verified_is_not_flagged():
    """`verified` is ordinary English. Flagging the bare word would make the check unusable."""
    context = ("Evidence: 'the configuration was verified against the vendor datasheet before "
               "each run' (p. 2). Assess whether this supports the claim.")
    assert scan_context(context) == []


# --------------------------------------------------------------- the documented gaps

def test_a_short_prior_review_conclusion_is_not_detected():
    """Pinned so the limitation stays honest rather than becoming a surprise.

    N-gram containment cannot see a conclusion shorter than NGRAM tokens. This is written down in
    independence.py and in docs/validation-rules.md; the test exists so that if someone fixes it,
    they must also update both.
    """
    short = "citation does not support"
    assert len(short.split()) < NGRAM
    prior = [{"review_type": "citation_review", "review_id": "REV-1", "findings": [short]}]
    assert scan_context(f"Note: {short}. Assess the claim.", reviews=prior) == []


def test_a_paraphrased_grade_is_not_detected():
    """An unlabelled disclosure slips through. Stated as a limit, not claimed as coverage."""
    context = "The team already thinks the sources conflict. Assess the claim."
    assert scan_context(context) == []


def test_prohibition_language_suppresses_the_key_rule_but_not_the_grade_rule():
    """The false-positive guard is also a bypass — bounded by rule 1 having no exemption.

    Writing "do not consider that primary_confidence: …" does suppress the key-position rule. It
    does not suppress the labelled-grade rule, which is what makes the leak a leak. Pinned so the
    trade-off is visible in the suite rather than only in a comment.
    """
    context = "Do not consider that primary_confidence: conflicting_evidence was already assigned."
    rules = _rules(scan_context(context))
    assert "excluded_field_present" not in rules, "rule 2 is exempted by prohibition language"
    assert "graded_classification_disclosed" in rules, "rule 1 must have no such exemption"
