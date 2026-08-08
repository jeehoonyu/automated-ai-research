"""Every domain vocabulary in the package, checked against the schema that defines it.

WHY THIS FILE EXISTS. The web UI's worst defect was not a typo — it was a shape. Two Jinja templates
each restated the Claim schema's `independent_review_status` enum from memory. Both blocked on
`unknown`, a value the schema does not contain, and both let `not_confirmed` and `not_yet_reviewed`
fall through to the branch that renders as fine. So a claim that had never been independently
reviewed displayed a green chip, while a claim that recorded *nothing* displayed a blocking one:
writing the truth down looked better than writing nothing.

The code beside it that was correct was correct for one reason — it asked `CheckResult.blocks`
instead of restating anything.

There are 53 enums across the 15 shipped schemas, and Python throughout this package restates slices
of them as sets, tuples, dict keys and inline membership tests. Every one is the same bet. These
tests take the enum from the shipped schema at runtime, so a schema that gains a member fails here
rather than landing silently in whichever branch nobody thought about.

TWO THINGS THIS CANNOT DO, stated so the green does not overclaim:

1. **Coverage is not correctness.** A vocabulary can name every member and file one in the wrong
   set. `not_confirmed` was mis-filed, not missing, and no test derived from the schema would have
   caught it — only reading it against `check_support_classifications` did. Where a set encodes a
   judgement, the test below pins the judgement explicitly rather than just its size.
2. **It says nothing about values that never reach the code.** A gap behind a schema constraint that
   forbids the value on write is untidy, not dangerous. Those are noted where they occur.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import research
from research.artifacts.registry import SCHEMA_FILES
from research.extraction.status import ExtractionStatus
from research.profiles import INDEPENDENCE_ORDER, KNOWN_METHODOLOGY_ITEMS
from research.reporting.language import MAX_STRENGTH, QUALIFIER
from research.runs.lifecycle import (
    STAGE_COMPLETES_INTO,
    STAGE_REQUIRES_PHASE,
    Disposition,
    Phase,
    Stage,
)
from research.runs.promotion import DESTINATION, STAGE_PHASE
from research.ui.views import CLAIM_ESTABLISHING
from research.validation.validator import (
    CHECKS,
    DEPENDENT_RELATIONSHIPS,
    INDEPENDENCE_ESTABLISHING,
    REQUIRED_REVIEWS,
    Status,
)

SCHEMA_DIR = Path(research.__file__).resolve().parent / "schemas" / "v1"


def enum_of(schema: str, *path: str) -> set[str]:
    """The enum at `path` in a shipped schema, read at runtime rather than copied here.

    Copying it would make this file another restatement — the exact thing it exists to prevent.
    """
    node: Any = json.loads((SCHEMA_DIR / schema).read_text(encoding="utf-8"))
    for part in path:
        node = node["properties"][part] if "properties" in node and part in node["properties"] \
            else node[part]
    assert isinstance(node.get("enum"), list), f"{schema}:{'.'.join(path)} has no enum"
    return set(node["enum"])


# --------------------------------------------------------------------- the enums ARE the schemas
#
# A StrEnum and a schema enum describing the same field is a duplication that happens to be
# load-bearing: artifacts are validated against the schema and manipulated through the enum. They
# must agree in BOTH directions — a phase the schema permits but the code cannot represent is as
# broken as the reverse.


@pytest.mark.parametrize(("enum_cls", "schema", "field"), [
    (Phase, "run-manifest.schema.json", "phase"),
    (Disposition, "run-manifest.schema.json", "disposition"),
    (ExtractionStatus, "document.schema.json", "extraction_status"),
], ids=lambda x: getattr(x, "__name__", x))
def test_str_enum_matches_its_schema_exactly(enum_cls: Any, schema: str, field: str):
    assert {str(m) for m in enum_cls} == enum_of(schema, field)


def test_the_four_check_statuses_match_the_validation_result_schema():
    from typing import get_args

    assert set(get_args(Status)) == enum_of("validation-result.schema.json", "checks",
                                            "items", "properties", "status")


def test_every_registered_schema_file_exists_and_every_file_is_registered():
    """`SCHEMA_FILES` is a hand-written map of artifact name to file stem. A schema on disk that
    nothing registers is unreachable; a registration with no file fails at the first write."""
    registered = {f"{stem}.schema.json" for stem in SCHEMA_FILES.values()}
    on_disk = {p.name for p in SCHEMA_DIR.glob("*.json")}
    assert registered == on_disk, {
        "registered but missing": sorted(registered - on_disk),
        "on disk but unregistered": sorted(on_disk - registered),
    }


# ------------------------------------------------------------------------------ total mappings
#
# A dict keyed by an enum that misses a member does not fail loudly — it raises a KeyError at the
# one moment that member occurs, or worse, is read with `.get()` and returns a default.


#: The two stages this package performs itself. They have no agent response to accept, so a mapping
#: about accepting agent work is complete without them. Named once, here, rather than assumed.
CLI_PERFORMED_STAGES = {Stage.FINAL_VALIDATION, Stage.REPORT}


@pytest.mark.parametrize(("name", "mapping"), [
    ("STAGE_COMPLETES_INTO", STAGE_COMPLETES_INTO),
    ("STAGE_REQUIRES_PHASE", STAGE_REQUIRES_PHASE),
])
def test_stage_mappings_are_total(name: str, mapping: dict[Stage, Phase]):
    assert set(mapping) == set(Stage), f"{name} is missing {sorted(set(Stage) - set(mapping))}"


def test_stage_phase_covers_exactly_the_stages_an_agent_performs():
    """`promotion.STAGE_PHASE` advances a run when a stage's responses are accepted. It omits the
    two stages the CLI performs itself — deliberately, and `parse_stage` refuses them by name."""
    assert set(STAGE_PHASE) == set(Stage) - CLI_PERFORMED_STAGES


def test_every_promotion_destination_is_a_real_artifact_type():
    """`DESTINATION` is keyed by SCHEMA NAME, not by stage: one stage may promote several kinds.
    A key here that the registry does not know is a promotion that could never validate."""
    assert set(DESTINATION) <= set(SCHEMA_FILES), sorted(set(DESTINATION) - set(SCHEMA_FILES))


@pytest.mark.parametrize("mapping_name", ["QUALIFIER", "MAX_STRENGTH"])
def test_report_language_covers_every_support_classification(mapping_name: str):
    """A classification missing from `QUALIFIER` renders as "Classification not recorded." — a
    published report describing a claim it could not label, in a renderer whose whole design is that
    it has no vocabulary of its own."""
    mapping = {"QUALIFIER": QUALIFIER, "MAX_STRENGTH": MAX_STRENGTH}[mapping_name]
    assert set(mapping) == enum_of("claim.schema.json", "support_classification")


def test_required_reviews_name_real_review_types():
    assert set(REQUIRED_REVIEWS) <= enum_of("review.schema.json", "review_type")


# ------------------------------------------------------------- partitions that encode a judgement
#
# These do not cover their enum, and must not. Each names a decision, and the decision is pinned
# here BY VALUE rather than by count — a count test passes when a member moves between sets, which
# is exactly how `not_confirmed` came to sit in the reassuring branch.


def test_every_relationship_type_is_classified_or_deliberately_neither():
    """`unknown` and `cites` are excluded from both sets on purpose, and the reason is a paragraph
    in validator.py: recording `unknown` must not clear the gate that recording nothing blocks, and
    a source that cites another may simply be repeating it."""
    deliberately_neither = {"unknown", "cites"}
    classified = DEPENDENT_RELATIONSHIPS | INDEPENDENCE_ESTABLISHING | deliberately_neither
    assert classified == enum_of("source-relationship.schema.json", "relationship_type")
    assert INDEPENDENCE_ESTABLISHING == {"independent"}
    assert not (DEPENDENT_RELATIONSHIPS & INDEPENDENCE_ESTABLISHING)


def test_independence_order_covers_the_review_status_enum():
    """`INDEPENDENCE_ORDER` is a ranking, so it must be total over the enum it ranks — an unranked
    value cannot be compared against a profile's minimum."""
    assert set(INDEPENDENCE_ORDER) == enum_of("review.schema.json", "review_independence",
                                              "properties", "status")


def test_independence_order_is_applied_to_the_claim_enum_and_fails_closed_on_the_extra_member():
    """THE CROSS-ENUM CASE. `INDEPENDENCE_ORDER` carries the 4 values of a Review's
    `review_independence.status`. A Claim's `independent_review_status` has 5 — it also has
    `not_yet_reviewed`. So the ranking is asked about a value it does not rank.

    That is safe only because both accessors test membership first and fail closed. This asserts the
    fail-closed behaviour rather than the absence of the gap, because the gap is inherent: the two
    enums genuinely differ, and a claim awaiting review has no review status to rank.
    """
    from research.profiles import Profile

    claim_only = enum_of("claim.schema.json", "independent_review_status") - set(
        INDEPENDENCE_ORDER)
    assert claim_only == {"not_yet_reviewed"}

    profile = Profile(name="test")
    for value in [*claim_only, None, "invented"]:
        assert profile.accepts_independence(value) is False, value
        assert profile.must_disclose_independence(value) is True, value


def test_the_ui_independence_vocabulary_matches_the_validator():
    """The defect this whole file exists because of. `check_support_classifications` treats None,
    `not_yet_reviewed`, `not_confirmed` and `not_independent` as independence NOT established; the
    UI must agree, and must derive its answer from the same reading."""
    establishing = CLAIM_ESTABLISHING["independent_review_status"]
    not_established = enum_of("claim.schema.json", "independent_review_status") - establishing
    assert not_established == {"not_yet_reviewed", "not_confirmed", "not_independent"}


def test_profile_methodology_items_are_things_a_review_can_record():
    """A profile may only require an item the Review schema can carry an assessment for. Requiring
    anything else would be a promise no code can keep."""
    assessments = json.loads(
        (SCHEMA_DIR / "review.schema.json").read_text(encoding="utf-8")
    )["properties"]["methodology_assessments"]
    assert assessments.get("propertyNames", {}).get("enum") is None or (
        KNOWN_METHODOLOGY_ITEMS <= set(assessments["propertyNames"]["enum"]))


# --------------------------------------------------- vocabularies now derived instead of restated
#
# Each of these was a hand-written list that named a subset of its enum. The sweep that found them
# checked one question of each: what does a value it does NOT list do? In every case below the
# answer was the reassuring one.


def test_the_leak_scanner_knows_every_support_classification():
    """It matched a hand-copied seven-element tuple. A classification added to the schema and not
    added there would simply stop being recognised as a leaked grade, and the scanner would report
    a clean reviewer context."""
    from research.validation.independence import SUPPORT_CLASSIFICATIONS

    assert set(SUPPORT_CLASSIFICATIONS) == enum_of("claim.schema.json", "support_classification")


def test_a_human_reviews_conclusions_are_withheld_from_an_independent_reviewer():
    """`PRIOR_REVIEW_TYPES` listed three of the five review types by hand and left out
    `human_review` — whose conclusions are exactly the kind of prior judgement an independent
    reviewer must not see. Derived by subtraction now, so a review type added later is excluded by
    default rather than waved through."""
    from research.validation.independence import PRIOR_REVIEW_TYPES

    review_types = enum_of("review.schema.json", "review_type")
    assert set(PRIOR_REVIEW_TYPES) == review_types - {"independent_review"}
    assert "human_review" in PRIOR_REVIEW_TYPES


def test_only_a_causal_claim_may_read_causally():
    """Named the three "correlational" types, so the other eight were exempt by omission. Inverted:
    naming the one exempt type makes a claim type added later suspect by default, which is the
    direction a disclosure flag should fail."""
    from research.reporting.language import CAUSAL_CLAIM_TYPES

    claim_types = enum_of("claim.schema.json", "claim_type")
    assert CAUSAL_CLAIM_TYPES == {"causal_claim"}
    assert CAUSAL_CLAIM_TYPES <= claim_types
    assert len(claim_types - CAUSAL_CLAIM_TYPES) == 10


def test_a_profile_cannot_prohibit_a_classification_that_does_not_exist(tmp_path: Path):
    """The one profile-supplied vocabulary loaded verbatim while its three neighbours all validated.
    A typo prohibited nothing, so the profile read as tighter than the default while being it."""
    import yaml

    from research.errors import InvalidArguments
    from research.profiles import load_profile

    directory = tmp_path / "profiles"
    directory.mkdir(parents=True)
    (directory / "typo.yaml").write_text(
        yaml.safe_dump({"name": "typo", "prohibited_confidence": ["moderatly_supported"]}),
        encoding="utf-8")

    with pytest.raises(InvalidArguments) as exc:
        load_profile("typo", tmp_path)
    assert "moderatly_supported" in str(exc.value.message) + str(exc.value.detail)


def test_every_extraction_status_but_extracted_is_disclosed_in_a_report():
    """`ocr_documents` tested two of the seven, so a source that failed to parse outright reached
    the Sources table with no disclosure at all."""
    from research.reporting.renderer import _extraction_needs_disclosure

    for status in enum_of("document.schema.json", "extraction_status"):
        assert _extraction_needs_disclosure(status) is (status != "extracted"), status


def test_evidence_the_package_calls_unreliable_needs_a_human():
    """`check_ocr_evidence` tested `== "ocr_required"` — one of seven — while the package's own
    `needs_human_review` predicate names four, and `Evidence.human_review_required`, a REQUIRED
    schema field, was read by nothing anywhere in `src/research`."""
    unreliable = {s for s in ExtractionStatus if s.needs_human_review}
    assert {str(s) for s in unreliable} == {"ambiguous", "ocr_required", "partially_extracted",
                                            "human_review_required"}
    assert not ExtractionStatus.EXTRACTED.needs_human_review


def test_the_schema_enum_accessor_refuses_a_field_with_no_enum():
    """It must raise rather than return an empty set: a vocabulary that quietly resolves to nothing
    would permit everything or forbid everything, and both beat a startup failure only in the sense
    that nobody notices."""
    from research.artifacts.registry import schema_enum
    from research.errors import SchemaValidationError

    assert schema_enum("Claim", "support_classification") == enum_of(
        "claim.schema.json", "support_classification")
    with pytest.raises(SchemaValidationError):
        schema_enum("Claim", "claim")


def test_every_support_classification_is_decided_to_owe_factors_or_not():
    """A new classification must not default into either half of the confidence gate.

    `SUPPORT_ASSERTING` splits the enum: those four owe factor ratings under spec §23, the rest
    assert no support and owe nothing. If a twelfth classification is added and this file is not
    touched, it silently lands in the exempt half — a new way to publish with no confidence
    recorded, arriving through a change that looks unrelated. Partitioning against the schema is
    what makes that a failing test rather than a discovery.
    """
    from research.validation.validator import SUPPORT_ASSERTING

    every = enum_of("claim.schema.json", "support_classification")
    exempt = {"conflicting_evidence", "unsupported", "unable_to_determine"}

    assert SUPPORT_ASSERTING <= every, SUPPORT_ASSERTING - every
    assert SUPPORT_ASSERTING | exempt == every, (
        f"undecided classification(s): {sorted(every - SUPPORT_ASSERTING - exempt)}")


# --------------------------------------------------------------------------- the docs' own copies


def test_the_documented_benchmark_coverage_matches_the_cases_that_exist():
    """`docs/validation-rules.md` claimed each of the eleven spec 8.8 blocking conditions had a
    benchmark case naming its check. Six did.

    The sentence was true when the list was shorter and was never revisited — a restatement like any
    other, rotting in the direction that flatters. This pins the corrected claim to the file it
    describes, so it cannot drift back by wishful editing. It deliberately compares the doc against
    `cases.json` rather than against a number typed here.
    """
    repo = Path(research.__file__).resolve().parents[2]
    cases = json.loads((repo / "benchmark" / "expected" / "cases.json").read_text(encoding="utf-8"))
    if isinstance(cases, dict):
        cases = cases.get("cases", [])

    # B10 declares a check/status pair its test never evaluates — it asserts `validate_artifact`
    # raises and never calls `validate_run` — so the pair is dead metadata, not coverage.
    evaluated = {str(c["expect_check"]) for c in cases
                 if c.get("expect_check") and str(c.get("id")) != "B10"}

    doc = (repo / "docs" / "validation-rules.md").read_text(encoding="utf-8")
    for name in evaluated:
        assert f"`{name}`" in doc, f"{name} has a benchmark case the documentation does not name"
    assert f"{len(evaluated)} of these eleven" in doc, (
        f"the documentation does not state that {len(evaluated)} of the eleven conditions have a "
        f"mechanism-naming benchmark case")


def test_no_document_states_a_stale_check_count():
    """Prose restating a vocabulary is a copy like any other, and a count is the copy that rots
    first.

    Phrased as "every count that IS stated must be right" rather than "these files must state it".
    Requiring a particular file to carry the number would be satisfied by deleting the sentence,
    which is not the property anyone wants; this way a stale number is a failure and no document is
    forced to repeat it.

    SCOPE, AND THE GAP IT LEAVES. Only documents that describe the system *as it is* are checked.
    `CHANGELOG.md` and `GOAL.md` are narratives: they record what was observed on a date — "22
    checks either way, verified" is evidence from a specific run, and editing it to 25 would falsify
    a record rather than update a fact. The cost is real and worth naming: a current-tense count in
    one of those two files could go stale and nothing here would notice.

    Which check *ids* the docs name is asserted in the integration suite against the ids a real run
    emits — a check's function name and its id are different strings, so deriving one from the other
    here would only test the derivation.
    """
    import re

    actual = len(CHECKS)
    repo = Path(research.__file__).resolve().parents[2]
    pattern = re.compile(r"\b(\d+)\s+(?:validation\s+)?checks\b")
    stale: list[str] = []
    for path in [repo / "README.md", *sorted((repo / "docs").glob("*.md"))]:
        for match in pattern.finditer(path.read_text(encoding="utf-8")):
            if int(match.group(1)) != actual:
                stale.append(f"{path.name}: {match.group(0)!r} but there are {actual}")
    assert not stale, stale
    assert f"{actual} checks" in (repo / "README.md").read_text(encoding="utf-8"), (
        "the README no longer states the check count at all")
