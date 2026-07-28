"""`research validate` — the gate.

THE CENTRAL RULE (spec §44). A statement is publishable only when it is a claim, referencing
evidence ids, resolving to immutable source bytes, whose citation genuinely supports it, whose
contradictions were considered, whose reviews completed, and whose human-review conditions were
resolved or disclosed. This module is where that is decided, and it decides by CHECKING rather than
by trusting what an artifact says about itself.

THREE OUTCOMES PER CHECK, NOT TWO
    passed          the check ran and the property holds
    failed          the check ran and the property does not hold
    not_evaluated   the check could NOT run — inputs missing, artifact unreadable
    not_applicable  the check does not apply to this run

`not_evaluated` blocks report eligibility exactly as `failed` does. This is the single most
important line in the file. An empty finding list is indistinguishable from a clean bill of health,
and a validator that silently skips what it cannot inspect reports "no problems found" for a run it
never looked at. (docs/lessons-carried-forward.md §6b, learned the hard way.)

CANDIDATE VS CANONICAL. Agents write to `responses/`. Nothing there is canonical. Validation
promotes a response into `evidence/`, `claims/`, `reviews/` only after it validates — so a file is
never authoritative merely because an agent created it (spec §28).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ..artifacts.io import make_artifact, read_artifact, write_artifact
from ..artifacts.locators import resolve_text_locator, resolve_visual_locator
from ..artifacts.registry import validate_artifact
from ..config import SCHEMA_VERSION, Workspace
from ..errors import ResearchError
from ..hashing import sha256_file, sha256_text
from ..runs.lifecycle import Disposition, Phase, Stage, is_valid_transition
from ..runs.manager import load_run
from ..security.paths import safe_join
from .independence import scan_context

Status = Literal["passed", "failed", "not_evaluated", "not_applicable"]

# Reviews that must exist before a report may be published (spec §8.8).
REQUIRED_REVIEWS = {
    "contradiction_review": Stage.CONTRADICTION_REVIEW,
    "citation_review": Stage.CITATION_REVIEW,
    "methodology_review": Stage.METHODOLOGY_REVIEW,
    "independent_review": Stage.INDEPENDENT_REVIEW,
}

# Independence the default profile will accept. High-risk profiles demand confirmed_independent.
ACCEPTABLE_INDEPENDENCE = {"confirmed_independent", "procedurally_isolated"}
STRICT_INDEPENDENCE = {"confirmed_independent"}


@dataclass
class CheckResult:
    check: str
    status: Status
    detail: str = ""
    artifact_ids: list[str] = field(default_factory=list)
    human_review: bool = False

    @property
    def blocks(self) -> bool:
        """`not_evaluated` blocks. See the module docstring — this is the whole point."""
        return self.status in ("failed", "not_evaluated")

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"check": self.check, "status": self.status}
        if self.detail:
            out["detail"] = self.detail
        if self.artifact_ids:
            out["artifact_ids"] = self.artifact_ids[:50]
        return out


@dataclass
class RunContext:
    """Everything validation needs, loaded once, with load failures recorded rather than raised."""

    ws: Workspace
    run_id: str
    manifest: dict[str, Any]
    plan: dict[str, Any] | None = None
    evidence: list[dict[str, Any]] = field(default_factory=list)
    claims: list[dict[str, Any]] = field(default_factory=list)
    reviews: list[dict[str, Any]] = field(default_factory=list)
    review_contexts: list[dict[str, Any]] = field(default_factory=list)
    documents: dict[str, dict[str, Any]] = field(default_factory=dict)
    load_errors: list[str] = field(default_factory=list)

    @property
    def profile(self) -> str:
        return str(self.manifest.get("profile", "default"))

    @property
    def high_risk(self) -> bool:
        return bool((self.plan or {}).get("high_risk")) or self.profile in {"medicine", "finance"}

    def evidence_by_id(self) -> dict[str, dict[str, Any]]:
        return {e["evidence_id"]: e for e in self.evidence}

    def normalized_text(self, document_id: str) -> str | None:
        doc = self.documents.get(document_id)
        if not doc or not doc.get("normalized_text_path"):
            return None
        path = self.ws.root / doc["normalized_text_path"]
        return path.read_text(encoding="utf-8") if path.is_file() else None

    def render_index(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for doc in self.documents.values():
            for page in doc.get("pages", []):
                if page.get("render"):
                    out[page["render"]["sha256"]] = page["render"]["path"]
        return out


def _load_json_dir(directory: Path) -> tuple[list[dict[str, Any]], list[str]]:
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    if not directory.is_dir():
        return items, errors
    for path in sorted(directory.glob("*.json")):
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{path.name}: unreadable ({type(exc).__name__}: {exc})")
            continue
        items.extend(data if isinstance(data, list) else [data])
    return items, errors


def build_context(ws: Workspace, run_id: str) -> RunContext:
    """Load canonical artifacts. Anything unreadable becomes a load error, never a silent skip."""
    manifest = load_run(ws, run_id)
    run_dir = safe_join(ws.root, "runs", run_id)
    ctx = RunContext(ws=ws, run_id=run_id, manifest=manifest)

    for name, target in (("evidence", "evidence"), ("claims", "claims"), ("reviews", "reviews"),
                         ("review_contexts", "review-contexts")):
        items, errors = _load_json_dir(run_dir / target)
        setattr(ctx, name, items)
        ctx.load_errors.extend(f"{target}/{e}" for e in errors)

    plan_path = run_dir / "plan.json"
    if plan_path.is_file():
        try:
            ctx.plan = read_artifact(plan_path, expect_schema="ResearchPlan")
        except ResearchError as exc:
            ctx.load_errors.append(f"plan.json: {exc.message}")

    for path in sorted(safe_join(ws.root, "documents", "manifests").glob("*.json")):
        try:
            doc = read_artifact(path, expect_schema="Document")
            ctx.documents[doc["document_id"]] = doc
        except ResearchError as exc:
            ctx.load_errors.append(f"{path.name}: {exc.message}")
    return ctx


# ============================================================ checks
# Each returns a CheckResult. A check that cannot run returns not_evaluated with the reason.


def check_artifacts_conform(ctx: RunContext) -> CheckResult:
    bad: list[str] = []
    for artifact in [*ctx.evidence, *ctx.claims, *ctx.reviews, *ctx.review_contexts,
                     *([ctx.plan] if ctx.plan else [])]:
        try:
            validate_artifact(artifact)
        except ResearchError as exc:
            bad.append(f"{artifact.get('artifact_id', '?')}: {exc.message}")
    if ctx.load_errors:
        return CheckResult("artifacts_conform_to_schema", "not_evaluated",
                           "some artifacts could not be read: " + "; ".join(ctx.load_errors[:5]))
    if bad:
        return CheckResult("artifacts_conform_to_schema", "failed", "; ".join(bad[:5]))
    return CheckResult("artifacts_conform_to_schema", "passed",
                       f"{len(ctx.evidence) + len(ctx.claims) + len(ctx.reviews)} artifact(s)")


def check_source_hashes(ctx: RunContext) -> CheckResult:
    """The originals must still hash to what was recorded. Evidence rests on those bytes."""
    if not ctx.documents:
        return CheckResult("source_hashes_match", "not_evaluated", "no documents in this workspace")
    mismatched: list[str] = []
    missing: list[str] = []
    for doc in ctx.documents.values():
        stored = ctx.ws.root / doc["stored_original"]
        if not stored.is_file():
            missing.append(doc["document_id"])
            continue
        if sha256_file(stored) != doc["source_sha256"]:
            mismatched.append(doc["document_id"])
    if missing:
        return CheckResult("source_hashes_match", "not_evaluated",
                           f"{len(missing)} original file(s) are absent", missing)
    if mismatched:
        return CheckResult("source_hashes_match", "failed",
                           f"{len(mismatched)} original(s) no longer hash to their recorded value",
                           mismatched)
    return CheckResult("source_hashes_match", "passed", f"{len(ctx.documents)} document(s)")


def check_evidence_references(ctx: RunContext) -> CheckResult:
    """Every evidence record must point at a document version this workspace actually holds."""
    if not ctx.evidence:
        # A run whose only conclusion is `unable_to_determine` legitimately has no evidence, and
        # spec §44 makes that a SUCCESSFUL outcome. Treating "no evidence" as unconditionally
        # not_evaluated made the sanctioned answer unpublishable — the benchmark's B9 case is what
        # exposed it. "Nothing to check" and "could not check" are different states.
        needs_evidence = [c for c in ctx.claims
                          if c.get("claim_type") != "insufficient_evidence_finding"]
        if ctx.claims and not needs_evidence:
            return CheckResult("evidence_references_resolve", "not_applicable",
                               "this run concluded unable_to_determine; no evidence was cited")
        return CheckResult("evidence_references_resolve", "not_evaluated",
                           "no evidence records have been produced")
    dangling: list[str] = []
    for ev in ctx.evidence:
        doc = ctx.documents.get(ev["document_id"])
        if doc is None:
            dangling.append(f"{ev['evidence_id']} -> unknown document {ev['document_id']}")
        elif doc["document_version_id"] != ev["document_version_id"]:
            dangling.append(
                f"{ev['evidence_id']} -> document version {ev['document_version_id']} "
                f"does not match the current extraction {doc['document_version_id']}")
    if dangling:
        return CheckResult("evidence_references_resolve", "failed", "; ".join(dangling[:5]),
                           [d.split(" ")[0] for d in dangling])
    return CheckResult("evidence_references_resolve", "passed", f"{len(ctx.evidence)} record(s)")


def check_text_locators(ctx: RunContext) -> CheckResult:
    """Re-slice the stored text and compare the span hash. This is citation resolution."""
    text_ev = [e for e in ctx.evidence if e["locator"].get("type") == "text_span"]
    if not text_ev:
        return CheckResult("text_locators_resolve", "not_applicable", "no text evidence")
    failures: list[str] = []
    unevaluated: list[str] = []
    for ev in text_ev:
        text = ctx.normalized_text(ev["document_id"])
        if text is None:
            unevaluated.append(ev["evidence_id"])
            continue
        result = resolve_text_locator(ev["locator"], text)
        if not result.ok:
            failures.append(f"{ev['evidence_id']}: {result.status} — {result.detail}")
        elif ev.get("exact_text") and result.text != ev["exact_text"]:
            failures.append(
                f"{ev['evidence_id']}: the locator resolves, but exact_text does not match the "
                f"passage at those offsets — the quote was edited or paraphrased")
    if unevaluated:
        return CheckResult("text_locators_resolve", "not_evaluated",
                           f"{len(unevaluated)} evidence record(s) reference a document whose "
                           f"normalized text is missing", unevaluated)
    if failures:
        return CheckResult("text_locators_resolve", "failed", "; ".join(failures[:5]))
    return CheckResult("text_locators_resolve", "passed", f"{len(text_ev)} locator(s) resolved")


def check_visual_locators(ctx: RunContext) -> CheckResult:
    visual = [e for e in ctx.evidence if e["locator"].get("type") == "visual_region"]
    if not visual:
        return CheckResult("visual_locators_resolve", "not_applicable", "no visual evidence")
    index = ctx.render_index()
    failures = []
    for ev in visual:
        result = resolve_visual_locator(ev["locator"], ctx.ws.root, index)
        if not result.ok:
            failures.append(f"{ev['evidence_id']}: {result.status} — {result.detail}")
    if failures:
        return CheckResult("visual_locators_resolve", "failed", "; ".join(failures[:5]))
    return CheckResult("visual_locators_resolve", "passed", f"{len(visual)} region(s)")


def check_claims_have_evidence(ctx: RunContext) -> CheckResult:
    if not ctx.claims:
        return CheckResult("claims_reference_evidence", "not_evaluated", "no claims produced")
    known = set(ctx.evidence_by_id())
    problems: list[str] = []
    for claim in ctx.claims:
        ids = claim.get("supporting_evidence_ids") or []
        if claim.get("claim_type") != "insufficient_evidence_finding" and not ids:
            problems.append(f"{claim['claim_id']}: no supporting evidence")
        for eid in ids + (claim.get("contradicting_evidence_ids") or []):
            if eid not in known:
                problems.append(f"{claim['claim_id']}: dangling evidence reference {eid}")
    if problems:
        return CheckResult("claims_reference_evidence", "failed", "; ".join(problems[:5]))
    return CheckResult("claims_reference_evidence", "passed", f"{len(ctx.claims)} claim(s)")


def check_citation_support(ctx: RunContext) -> CheckResult:
    """A citation that is merely RELATED must never be counted as support (spec §38.5)."""
    if not ctx.claims:
        return CheckResult("citations_support_their_claims", "not_evaluated", "no claims produced")
    reviews = [r for r in ctx.reviews if r["review_type"] == "citation_review"]
    if not reviews:
        return CheckResult("citations_support_their_claims", "not_evaluated",
                           "no citation review has been performed")
    judged: dict[str, str] = {}
    for review in reviews:
        for entry in review.get("per_claim", []):
            if entry.get("citation_support"):
                judged[entry["claim_id"]] = entry["citation_support"]
    unjudged = [c["claim_id"] for c in ctx.claims
                if c.get("claim_type") != "insufficient_evidence_finding"
                and c["claim_id"] not in judged]
    if unjudged:
        return CheckResult("citations_support_their_claims", "not_evaluated",
                           f"{len(unjudged)} claim(s) were never assessed by citation review",
                           unjudged)
    bad = [cid for cid, verdict in judged.items()
           if verdict in ("related_not_supporting", "failed")]
    if bad:
        return CheckResult("citations_support_their_claims", "failed",
                           f"{len(bad)} claim(s) rest on citations that do not support them", bad)
    partial = [cid for cid, verdict in judged.items() if verdict == "partially_supported"]
    return CheckResult("citations_support_their_claims", "passed",
                       f"{len(judged)} claim(s) assessed"
                       + (f"; {len(partial)} only partially supported" if partial else ""),
                       human_review=bool(partial))


def _review_check(ctx: RunContext, review_type: str) -> CheckResult:
    name = f"{review_type}_complete"
    matching = [r for r in ctx.reviews if r["review_type"] == review_type]
    if not matching:
        return CheckResult(name, "not_evaluated", f"no {review_type} artifact was produced")
    failed = [r for r in matching if r["decision"] == "failed"]
    if failed:
        return CheckResult(name, "failed",
                           "; ".join(i for r in failed for i in r.get("blocking_issues", []))[:400],
                           [r["review_id"] for r in failed])
    incomplete = [r for r in matching if r["decision"] == "incomplete"]
    if incomplete:
        return CheckResult(name, "not_evaluated", f"{review_type} is incomplete",
                           [r["review_id"] for r in incomplete])
    needs_human = [r for r in matching if r["decision"] == "human_review_required"]
    return CheckResult(name, "passed", f"{len(matching)} review(s)",
                       [r["review_id"] for r in matching], human_review=bool(needs_human))


def check_independence(ctx: RunContext) -> CheckResult:
    """Independence must be declared, and must meet the profile's bar (spec §13)."""
    reviews = [r for r in ctx.reviews if r["review_type"] == "independent_review"]
    if not reviews:
        return CheckResult("reviewer_independence_sufficient", "not_evaluated",
                           "no independent review was produced")
    acceptable = STRICT_INDEPENDENCE if ctx.high_risk else ACCEPTABLE_INDEPENDENCE
    statuses = [(r["review_id"], (r.get("review_independence") or {}).get("status"))
                for r in reviews]
    undeclared = [rid for rid, status in statuses if not status]
    if undeclared:
        return CheckResult("reviewer_independence_sufficient", "not_evaluated",
                           "independence was not declared", undeclared)
    insufficient = [rid for rid, status in statuses if status not in acceptable]
    if insufficient:
        return CheckResult(
            "reviewer_independence_sufficient", "failed",
            f"independence status is below the bar for this profile "
            f"(required: {sorted(acceptable)})", insufficient)
    # procedurally_isolated is acceptable by default but MUST be disclosed in the report.
    weak = [rid for rid, status in statuses if status == "procedurally_isolated"]
    return CheckResult("reviewer_independence_sufficient", "passed",
                       "procedurally_isolated — must be disclosed in the report" if weak
                       else "confirmed_independent",
                       [rid for rid, _ in statuses])


def check_independence_attested(ctx: RunContext) -> CheckResult:
    """`confirmed_independent` must be shown, not declared.

    `check_independence` above reads a status the host wrote about itself. That was the platform's
    one purely self-reported gate, and a real conformance run leaked `primary_confidence` into an
    independent-review packet without a single check noticing.

    So the strongest status now costs something: a `ReviewContext` artifact recording the text the
    host attests it handed the reviewer, which this check scans for excluded material drawn from the
    run's own artifacts (see validation/independence.py).

    The weaker statuses are unchanged. `procedurally_isolated` claims only that a fresh context was
    requested, needs no attestation, and must be disclosed in the report — it was always the honest
    option for a host that cannot prove more, and it still is.

    WHAT A PASS MEANS. The host's account of what it sent contains no leak of a shape this can
    detect. It does not mean the review was independent; a host that sends a leaky context and
    attests a clean one passes. The gain is that omitting evidence is no longer free and an
    accidental leak is now caught.
    """
    name = "independence_context_attested"
    reviews = [r for r in ctx.reviews if r["review_type"] == "independent_review"]
    if not reviews:
        return CheckResult(name, "not_applicable", "no independent review to attest")

    contexts_by_review: dict[str, list[dict[str, Any]]] = {}
    for context in ctx.review_contexts:
        contexts_by_review.setdefault(str(context.get("review_id")), []).append(context)

    unattested: list[str] = []
    incomplete: list[str] = []
    leaking: list[str] = []
    checked: list[str] = []

    for review in reviews:
        rid = review["review_id"]
        status = (review.get("review_independence") or {}).get("status")
        attached = contexts_by_review.get(rid, [])

        if not attached:
            # Only the strongest status requires proof. Anything weaker is already telling the
            # truth about how much it knows.
            if status == "confirmed_independent":
                unattested.append(rid)
            continue

        for context in attached:
            content = context.get("content", "")
            recorded = context.get("content_sha256")
            if recorded and sha256_text(content) != recorded:
                leaking.append(f"{rid}: attested content does not match its recorded "
                               f"content_sha256")
                continue
            attestation = context.get("attestation") or {}
            leaks = scan_context(content, reviews=ctx.reviews)
            if leaks:
                leaking.append(f"{rid}: " + "; ".join(leak.describe() for leak in leaks[:3]))
            elif not attestation.get("complete"):
                # A clean scan of a partial record proves nothing: the leak may be in the part that
                # was not recorded. Reporting this as a pass is the fail-open shape exactly.
                incomplete.append(f"{rid}: context is attested as incomplete "
                                  f"({attestation.get('method', 'unspecified')}), so a clean scan "
                                  f"establishes nothing")
            else:
                checked.append(rid)

    if leaking:
        return CheckResult(name, "failed",
                           "excluded material found in the attested reviewer context: "
                           + "; ".join(leaking[:3])
                           + " — this review is not independent, whatever it declares",
                           [r.split(":")[0] for r in leaking], human_review=True)
    if unattested:
        return CheckResult(
            name, "not_evaluated",
            "`confirmed_independent` was declared without a ReviewContext artifact, so nothing was "
            "checked. Attest the context the reviewer received, or declare "
            "`procedurally_isolated`, which does not assert a verified context.",
            unattested)
    if incomplete:
        return CheckResult(name, "not_evaluated", "; ".join(incomplete[:3]),
                           [i.split(":")[0] for i in incomplete])
    if checked:
        return CheckResult(name, "passed",
                           f"{len(checked)} attested context(s) scanned, no excluded material of a "
                           f"detectable shape", checked)
    return CheckResult(name, "not_applicable",
                       "no review declares `confirmed_independent`, so no attestation is required")


def check_ocr_evidence(ctx: RunContext) -> CheckResult:
    """OCR-required material may back a claim only through a recorded human verification."""
    ocr = [e for e in ctx.evidence if e.get("extraction_status") == "ocr_required"]
    if not ocr:
        return CheckResult("ocr_evidence_human_verified", "not_applicable",
                           "no evidence depends on an ocr_required page")
    verified = {a.get("target_artifact_id") for a in _amendments(ctx)
                if a.get("amendment_type") == "human_ocr_verification"}
    unverified = [e["evidence_id"] for e in ocr if e["evidence_id"] not in verified]
    if unverified:
        return CheckResult("ocr_evidence_human_verified", "failed",
                           f"{len(unverified)} evidence record(s) rest on an ocr_required page "
                           f"without a recorded human verification amendment", unverified,
                           human_review=True)
    return CheckResult("ocr_evidence_human_verified", "passed", f"{len(ocr)} verified")


def check_visual_certainty(ctx: RunContext) -> CheckResult:
    uncertain = [e["evidence_id"] for e in ctx.evidence
                 if e.get("interpretation_status") in ("uncertain", "human_review_required")]
    if not uncertain:
        return CheckResult("visual_interpretation_certain", "passed", "no uncertain readings")
    verified = {a.get("target_artifact_id") for a in _amendments(ctx)
                if a.get("amendment_type") == "human_visual_verification"}
    outstanding = [e for e in uncertain if e not in verified]
    if outstanding:
        return CheckResult("visual_interpretation_certain", "failed",
                           f"{len(outstanding)} visual reading(s) are uncertain and unverified",
                           outstanding, human_review=True)
    return CheckResult("visual_interpretation_certain", "passed", "all verified by a human")


def check_contradictions_disclosed(ctx: RunContext) -> CheckResult:
    unresolved = [c["claim_id"] for c in ctx.claims
                  if c.get("contradiction_status") == "unresolved"]
    if not unresolved:
        return CheckResult("contradictions_disclosed", "passed", "none unresolved")
    return CheckResult("contradictions_disclosed", "failed",
                       f"{len(unresolved)} claim(s) carry an unresolved contradiction; these must "
                       f"be disclosed and human-reviewed before publication", unresolved,
                       human_review=True)


def check_support_classifications(ctx: RunContext) -> CheckResult:
    """Enforce what the schema cannot: `verified` also requires a completed independent review."""
    if not ctx.claims:
        return CheckResult("support_classifications_earned", "not_evaluated", "no claims produced")
    independent = {r["review_id"] for r in ctx.reviews
                   if r["review_type"] == "independent_review" and r["decision"] in
                   ("passed", "passed_with_warnings")}
    problems: list[str] = []
    for claim in ctx.claims:
        cls = claim.get("support_classification")
        if cls == "verified":
            if not independent:
                problems.append(f"{claim['claim_id']}: `verified` requires a passed independent "
                                f"review; none exists")
            if claim.get("independent_review_status") in (None, "not_yet_reviewed",
                                                          "not_confirmed", "not_independent"):
                problems.append(f"{claim['claim_id']}: `verified` requires established reviewer "
                                f"independence")
        if cls == "strongly_supported" and len(claim.get("supporting_evidence_ids") or []) < 2:
            problems.append(f"{claim['claim_id']}: `strongly_supported` needs multiple evidence "
                            f"records")
    if problems:
        return CheckResult("support_classifications_earned", "failed", "; ".join(problems[:5]))
    return CheckResult("support_classifications_earned", "passed", f"{len(ctx.claims)} claim(s)")


# Relationships that make two documents NOT independent sources of the same fact.
DEPENDENT_RELATIONSHIPS = {
    "duplicate", "republication", "revision_of", "translation_of", "summarizes",
    "derived_from", "shares_primary_dataset", "shares_experimental_result",
}


def check_source_independence(ctx: RunContext) -> CheckResult:
    """Spec §24: multiple documents are not automatically multiple independent sources.

    This is the mistake that makes a single study look like a literature. A finding republished as
    an industry brief, a preprint and its journal version, or three papers reusing one dataset are
    ONE source wearing several hats — and a claim resting on them is not corroborated, merely
    repeated.

    `unknown` independence is never promoted to independent: a multi-source claim whose sources were
    never assessed returns `not_evaluated`, which blocks, rather than passing by default.
    """
    # ONLY `strongly_supported` requires independent corroboration (spec §23.2). `verified` does
    # NOT: it is reserved for DIRECTLY CHECKABLE facts, and the specification's own examples — a
    # paper's stated publication date, a directly reported sample size, a documented configuration
    # value — are single-source by their nature. A study's own account of its method has exactly one
    # authoritative source, and demanding a second one would make `verified` unreachable for the
    # facts it exists to describe.
    #
    # An earlier version required independence for both, which a conformance run caught by refusing
    # `verified` on a correctly-scoped single-source fact.
    needs = [c for c in ctx.claims
             if c.get("support_classification") == "strongly_supported"]
    if not needs:
        return CheckResult("source_independence_established", "not_applicable",
                           "no claim asserts strong support (only `strongly_supported` requires "
                           "independent corroboration)")

    evidence_by_id = ctx.evidence_by_id()
    relationships = _relationships(ctx)
    pairs: dict[frozenset[str], str] = {}
    for rel in relationships:
        key = frozenset({rel["source_document_id"], rel["related_document_id"]})
        pairs[key] = rel["relationship_type"]

    dependent: list[str] = []
    unassessed: list[str] = []
    for claim in needs:
        docs = sorted({evidence_by_id[e]["document_id"]
                       for e in claim.get("supporting_evidence_ids", [])
                       if e in evidence_by_id})
        if len(docs) < 2:
            # `strongly_supported` explicitly means corroborated by multiple independent sources,
            # so one document cannot earn it. (`verified` is not routed here at all.)
            dependent.append(f"{claim['claim_id']}: rests on one document, so it cannot be "
                             f"strongly_supported — that classification means multiple "
                             f"independent sources agree")
            continue
        for i, a in enumerate(docs):
            for b in docs[i + 1:]:
                kind = pairs.get(frozenset({a, b}))
                if kind is None:
                    unassessed.append(f"{claim['claim_id']}: independence of {a[:24]}… and "
                                      f"{b[:24]}… was never assessed")
                elif kind in DEPENDENT_RELATIONSHIPS:
                    dependent.append(f"{claim['claim_id']}: its sources are related by "
                                     f"'{kind}', so they are not independent corroboration")

    if dependent:
        return CheckResult("source_independence_established", "failed", "; ".join(dependent[:5]),
                           [d.split(":")[0] for d in dependent])
    if unassessed:
        return CheckResult("source_independence_established", "not_evaluated",
                           "; ".join(unassessed[:5]) +
                           " — unknown independence cannot be promoted to independent",
                           [u.split(":")[0] for u in unassessed])
    return CheckResult("source_independence_established", "passed",
                       f"{len(needs)} strongly-supported claim(s) rest on independent sources")


def _relationships(ctx: RunContext) -> list[dict[str, Any]]:
    items, _ = _load_json_dir(safe_join(ctx.ws.root, "runs", ctx.run_id) / "relationships")
    return [r for r in items if r.get("schema_name") == "SourceRelationship"]


def check_lifecycle(ctx: RunContext) -> CheckResult:
    """Replay the event log: every recorded transition must have been legal."""
    path = safe_join(ctx.ws.root, "runs", ctx.run_id) / "events.jsonl"
    if not path.is_file():
        return CheckResult("lifecycle_transitions_valid", "not_evaluated", "no event log")
    illegal: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("event") != "lifecycle_transition":
            continue
        prev, new = event.get("previous_phase"), event.get("new_phase")
        if prev == new:
            continue
        ok, reason = is_valid_transition(Phase(prev), Phase(new),
                                         Disposition(event.get("previous_disposition", "active")))
        if not ok:
            illegal.append(f"{prev} -> {new}: {reason}")
    if illegal:
        return CheckResult("lifecycle_transitions_valid", "failed", "; ".join(illegal[:5]))
    return CheckResult("lifecycle_transitions_valid", "passed", "event log replays cleanly")


def _amendments(ctx: RunContext) -> list[dict[str, Any]]:
    items, _ = _load_json_dir(safe_join(ctx.ws.root, "runs", ctx.run_id) / "amendments")
    return items


CHECKS = [
    check_artifacts_conform,
    check_source_hashes,
    check_evidence_references,
    check_text_locators,
    check_visual_locators,
    check_claims_have_evidence,
    check_citation_support,
    lambda ctx: _review_check(ctx, "contradiction_review"),
    lambda ctx: _review_check(ctx, "citation_review"),
    lambda ctx: _review_check(ctx, "methodology_review"),
    lambda ctx: _review_check(ctx, "independent_review"),
    check_independence,
    check_independence_attested,
    check_ocr_evidence,
    check_visual_certainty,
    check_contradictions_disclosed,
    check_support_classifications,
    check_source_independence,
    check_lifecycle,
]


def validate_run(ws: Workspace, run_id: str) -> dict[str, Any]:
    """Run every check and decide report eligibility."""
    ctx = build_context(ws, run_id)
    results = [check(ctx) for check in CHECKS]

    blocking = [r for r in results if r.blocks]
    human_review_reasons = [f"{r.check}: {r.detail}" for r in results if r.human_review]
    human_review_required = bool(human_review_reasons)
    report_eligible = not blocking and not human_review_required

    body = {
        "run_id": run_id,
        "validated_at": None,
        "report_eligible": report_eligible,
        "checks": [r.to_dict() for r in results],
        "blocking_errors": [
            {"check": r.check, "status": r.status, "detail": r.detail,
             "artifact_ids": r.artifact_ids[:20]}
            for r in blocking
        ],
        "warnings": [],
        "human_review_required": human_review_required,
        "human_review_reasons": human_review_reasons,
        "schema_versions_used": {"ValidationResult": SCHEMA_VERSION},
    }
    body.pop("validated_at")
    artifact = make_artifact(schema_name="ValidationResult", artifact_id=run_id, body=body,
                             actor_type="cli")
    path = safe_join(ws.root, "runs", run_id, "validation", "validation-result.json")
    write_artifact(path, artifact, root=ws.root)

    return {
        "run_id": run_id,
        "report_eligible": report_eligible,
        "checks": artifact["checks"],
        "passed": sum(1 for r in results if r.status == "passed"),
        "failed": sum(1 for r in results if r.status == "failed"),
        "not_evaluated": sum(1 for r in results if r.status == "not_evaluated"),
        "not_applicable": sum(1 for r in results if r.status == "not_applicable"),
        "blocking_errors": artifact["blocking_errors"],
        "human_review_required": human_review_required,
        "human_review_reasons": human_review_reasons,
        "validation_result_path": str(path),
        "validation_result_hash": artifact["artifact_hash"],
    }
