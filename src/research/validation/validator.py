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
from ..extraction.status import ExtractionStatus
from ..hashing import canonical_json, sha256_file, sha256_text, verify_artifact_hash
from ..profiles import Profile, load_profile
from ..reporting.language import scan_claims
from ..runs.lifecycle import Disposition, LifecycleError, Phase, Stage, is_valid_transition
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

# Human-review triggers are no longer hard-coded here. Each check names its trigger and asks the
# run's profile whether that condition forces human review; see src/research/profiles.py. A
# profile that omits a trigger is deliberately choosing not to require review for it — both
# shipped profiles list all six, so today nothing is loosened.


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
    relationships: list[dict[str, Any]] = field(default_factory=list)
    amendments: list[dict[str, Any]] = field(default_factory=list)
    retrieval: list[dict[str, Any]] = field(default_factory=list)
    documents: dict[str, dict[str, Any]] = field(default_factory=dict)
    load_errors: list[str] = field(default_factory=list)

    profile_rules: Profile | None = None
    profile_error: str | None = None

    @property
    def profile(self) -> str:
        return str(self.manifest.get("profile", "default"))

    @property
    def rules(self) -> Profile:
        """The loaded profile. Falls back to the built-in defaults ONLY when nothing loaded, and
        `check_profile_loaded` blocks in that case, so a run is never validated under rules that
        silently differ from the ones its manifest names."""
        return self.profile_rules or Profile(name=self.profile)

    @property
    def high_risk(self) -> bool:
        return bool((self.plan or {}).get("high_risk")) or self.rules.high_risk

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
    """Load canonical artifacts, VERIFYING each one's `artifact_hash`.

    This used to be a bare `json.load`. `read_artifact` verifies hashes; this loader did not, and
    this loader is what validation actually uses — so every artifact an untrusted host agent
    produces (evidence, claims, reviews, relationships, amendments) could be hand-edited after the
    fact and no gate would notice. One word changed in a citation review flips
    `citations_support_their_claims` from failed to passed and `report_eligible` to True.

    That made three shipped statements false at once: docs/security-model.md's "Reading verifies
    it. An artifact edited outside the amendment process is rejected, not repaired", gate 38.8's
    "hashes verified on read", and the module docstring above, which says this file "decides by
    CHECKING rather than by trusting what an artifact says about itself".

    A mismatch is a LOAD ERROR, not a skipped file: `check_artifacts_conform` turns load errors
    into `not_evaluated`, which blocks. Dropping a tampered artifact silently would let deleting
    the evidence for a failing gate make the gate pass.
    """
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
        for artifact in (data if isinstance(data, list) else [data]):
            if not isinstance(artifact, dict) or "artifact_hash" not in artifact:
                # Also stops a stray blob in `reviews/` from reaching a check that reads
                # `review_type` and dying with a KeyError instead of reporting not_evaluated.
                errors.append(f"{path.name}: not a canonical artifact (no artifact_hash)")
                continue
            if not verify_artifact_hash(artifact):
                errors.append(f"{path.name}: artifact_hash does not match its content — edited "
                              f"outside the amendment process")
                continue
            items.append(artifact)
    return items, errors


def build_context(ws: Workspace, run_id: str) -> RunContext:
    """Load canonical artifacts. Anything unreadable becomes a load error, never a silent skip."""
    manifest = load_run(ws, run_id)
    run_dir = safe_join(ws.root, "runs", run_id)
    ctx = RunContext(ws=ws, run_id=run_id, manifest=manifest)

    # Relationships and amendments are loaded HERE rather than lazily, so that their load errors
    # reach `ctx.load_errors` and so that `validated_inputs` below can name every artifact this
    # verdict was computed over. Loading them lazily meant a malformed one was silently dropped.
    for name, target in (("evidence", "evidence"), ("claims", "claims"), ("reviews", "reviews"),
                         ("review_contexts", "review-contexts"),
                         ("relationships", "relationships"), ("amendments", "amendments"),
                         ("retrieval", "retrieval")):
        items, errors = _load_json_dir(run_dir / target)
        setattr(ctx, name, items)
        ctx.load_errors.extend(f"{target}/{e}" for e in errors)

    # The rules a run is judged by come from the profile its manifest names. A failure to load is
    # NOT a fall back to the defaults — `check_profile_loaded` blocks — because validating a
    # `medicine` run under the standard bar while the manifest records `medicine` would be a run
    # whose stated rules and applied rules differ.
    try:
        ctx.profile_rules = load_profile(ctx.profile, ws.root)
    except ResearchError as exc:
        ctx.profile_error = exc.message

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
                     *ctx.relationships, *ctx.amendments,
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


def check_derived_text_hashes(ctx: RunContext) -> CheckResult:
    """The normalized text must still hash to what extraction recorded.

    `check_source_hashes` above re-hashes `originals/` and says "evidence rests on those bytes".
    It does not. A text locator is an offset pair into `normalized_text_path`, and `exact_text` is
    compared against a slice of THAT file — a derived, mutable artifact that nothing re-hashed.
    Any process with write access to the workspace could change the words a citation resolves to,
    and every gate still passed, under a report whose Method section tells the reader the evidence
    resolves to immutable source bytes.

    Worse, the renderer deliberately quotes through the locator rather than from
    `evidence["exact_text"]`, reasoning that validation would have caught a divergence. So the one
    defence-in-depth measure was what carried altered text into `report.md`.

    A document whose manifest records no `normalized_text_sha256` returns `not_evaluated` rather
    than being skipped: an older manifest that cannot be checked must block, not pass quietly.
    """
    name = "derived_text_hashes_match"
    relevant = [doc for doc in ctx.documents.values() if doc.get("normalized_text_path")]
    if not relevant:
        return CheckResult(name, "not_applicable", "no document has normalized text")

    unverifiable: list[str] = []
    missing: list[str] = []
    mismatched: list[str] = []
    for doc in relevant:
        recorded = doc.get("normalized_text_sha256")
        if not recorded:
            unverifiable.append(doc["document_id"])
            continue
        path = ctx.ws.root / doc["normalized_text_path"]
        if not path.is_file():
            missing.append(doc["document_id"])
            continue
        if sha256_text(path.read_text(encoding="utf-8")) != recorded:
            mismatched.append(doc["document_id"])

    if mismatched:
        return CheckResult(name, "failed",
                           f"{len(mismatched)} document(s) have normalized text that no longer "
                           f"hashes to its recorded value — every citation into them resolves to "
                           f"different words than were extracted", mismatched)
    if missing:
        return CheckResult(name, "not_evaluated",
                           f"{len(missing)} document(s) have no normalized text file, so citations "
                           f"into them cannot be checked", missing)
    if unverifiable:
        return CheckResult(name, "not_evaluated",
                           f"{len(unverifiable)} document(s) record no normalized_text_sha256, so "
                           f"the text citations resolve against cannot be verified", unverifiable)
    return CheckResult(name, "passed", f"{len(relevant)} document(s)")


def check_retrieval_provenance(ctx: RunContext) -> CheckResult:
    """Which searches produced this evidence, and were they run against this run's corpus?

    Spec §29 requires retrieval provenance. `research search` computed the entire record and a
    stable `retrieval_log_hash` and then discarded it, so nothing recorded how the evidence was
    found — while reports asserted the search was reproducible.

    Evidence can legitimately arrive without a search: a host may cite a passage found through
    `research inspect`. So an absent record is `not_evaluated` (unknown, therefore blocking) rather
    than `failed` (known-bad), and a run that genuinely used no search says so by recording none and
    accepting that it cannot claim retrieval provenance.
    """
    name = "retrieval_provenance_recorded"
    logs = [r for r in ctx.retrieval if r.get("schema_name") == "RetrievalLog"]
    if not ctx.evidence:
        return CheckResult(name, "not_applicable", "no evidence to account for")
    if not logs:
        return CheckResult(name, "not_evaluated",
                           "no retrieval record: which queries produced this evidence is unknown. "
                           "Run `research search ... --run <run-id>`, or record that the evidence "
                           "was located another way.")

    pinned = ctx.manifest.get("source_collection", {}).get("index_hash")
    wrong_corpus = [log["retrieval_id"] for log in logs if log.get("index_hash") != pinned]
    if wrong_corpus:
        return CheckResult(name, "failed",
                           f"{len(wrong_corpus)} search(es) ran against a different index than the "
                           f"one this run pinned ({pinned}); their results describe another corpus",
                           wrong_corpus)
    return CheckResult(name, "passed",
                       f"{len(logs)} search(es) recorded against the run's pinned index")


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
    # COLLECT, do not overwrite. This was `judged[claim_id] = verdict` inside a loop over every
    # citation review, so a second review saying `passed` ERASED an earlier
    # `related_not_supporting` — and which one won depended on filename sort order in
    # `_load_json_dir`. Re-reviewing until the answer is acceptable is precisely the behaviour a
    # citation gate exists to prevent, and it required no tampering at all.
    #
    # `not_checked` is excluded here: it is a real enum value meaning "not assessed", and treating
    # it as a verdict let an unjudged claim skip the `unjudged` path below because the dict key
    # existed.
    verdicts: dict[str, set[str]] = {}
    reviewers: dict[str, list[str]] = {}
    for review in reviews:
        for entry in review.get("per_claim", []):
            support = entry.get("citation_support")
            if not support or support == "not_checked":
                continue
            verdicts.setdefault(entry["claim_id"], set()).add(support)
            reviewers.setdefault(entry["claim_id"], []).append(review["review_id"])

    unjudged = [c["claim_id"] for c in ctx.claims
                if c.get("claim_type") != "insufficient_evidence_finding"
                and c["claim_id"] not in verdicts]
    if unjudged:
        return CheckResult("citations_support_their_claims", "not_evaluated",
                           f"{len(unjudged)} claim(s) were never assessed by citation review",
                           unjudged)

    disputed = sorted(cid for cid, seen in verdicts.items() if len(seen) > 1)
    if disputed:
        detail = "; ".join(
            f"{cid}: reviews disagree ({', '.join(sorted(verdicts[cid]))}) — "
            f"{', '.join(reviewers[cid])}" for cid in disputed[:3])
        return CheckResult("citations_support_their_claims", "not_evaluated",
                           f"{len(disputed)} claim(s) have conflicting citation verdicts, so which "
                           f"one holds is undecided: {detail}", disputed)

    judged = {cid: next(iter(seen)) for cid, seen in verdicts.items()}
    bad = [cid for cid, verdict in judged.items()
           if verdict in ("related_not_supporting", "failed")]
    if bad:
        return CheckResult("citations_support_their_claims", "failed",
                           f"{len(bad)} claim(s) rest on citations that do not support them", bad)
    partial = [cid for cid, verdict in judged.items() if verdict == "partially_supported"]
    return CheckResult("citations_support_their_claims", "passed",
                       f"{len(judged)} claim(s) assessed"
                       + (f"; {len(partial)} only partially supported" if partial else ""),
                       human_review=bool(partial)
                       and ctx.rules.forces_human_review("citation_failed_or_partial"))


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


def check_profile_loaded(ctx: RunContext) -> CheckResult:
    """The rules a run is judged by must be the rules its manifest names.

    Before profiles were loaded at all, this could not fail — `medicine` meant one hard-coded
    independence bar and nothing else, and every other rule the profile file described was inert.
    Now that the file decides, a file that will not load has to block: validating under the built-in
    defaults while the manifest records `medicine` produces a run whose stated rules and applied
    rules differ, which is worse than refusing.
    """
    name = "profile_rules_loaded"
    if ctx.profile_error:
        return CheckResult(name, "not_evaluated",
                           f"profile {ctx.profile!r} could not be loaded, so the rules this run "
                           f"should be judged by are unknown: {ctx.profile_error}")
    rules = ctx.rules
    detail = f"profile {rules.name!r} (risk={rules.risk}, minimum independence "
    detail += f"{rules.minimum_independence})"
    if rules.unimplemented:
        detail += f"; keys present but NOT enforced: {', '.join(rules.unimplemented)}"
    return CheckResult(name, "passed", detail)


def check_profile_confidence_permitted(ctx: RunContext) -> CheckResult:
    """A profile may forbid a classification outright, whatever the evidence.

    `medicine.yaml` has said `prohibited_confidence: [verified]` since it was written, and nothing
    read it. It does now.
    """
    name = "profile_confidence_permitted"
    forbidden = set(ctx.rules.prohibited_confidence)
    if not forbidden:
        return CheckResult(name, "not_applicable",
                           f"profile {ctx.rules.name!r} forbids no classification outright")
    if not ctx.claims:
        return CheckResult(name, "not_evaluated", "no claims produced")
    offending = [c["claim_id"] for c in ctx.claims
                 if c.get("support_classification") in forbidden]
    if offending:
        return CheckResult(name, "failed",
                           f"profile {ctx.rules.name!r} forbids "
                           f"{sorted(forbidden)} and {len(offending)} claim(s) carry it",
                           offending)
    return CheckResult(name, "passed",
                       f"no claim carries a classification this profile forbids "
                       f"({sorted(forbidden)})")


def check_independence(ctx: RunContext) -> CheckResult:
    """Independence must be declared, and must meet the profile's bar (spec §13)."""
    reviews = [r for r in ctx.reviews if r["review_type"] == "independent_review"]
    if not reviews:
        return CheckResult("reviewer_independence_sufficient", "not_evaluated",
                           "no independent review was produced")
    rules = ctx.rules
    # The bar comes from the profile file now, not from a hard-coded pair of sets. `high_risk` from
    # the plan still tightens it, because a plan may mark one question high-risk inside an
    # otherwise standard profile.
    minimum = ("confirmed_independent" if ctx.high_risk
               and rules.minimum_independence != "confirmed_independent"
               else rules.minimum_independence)
    statuses = [(r["review_id"], (r.get("review_independence") or {}).get("status"))
                for r in reviews]
    undeclared = [rid for rid, status in statuses if not status]
    if undeclared:
        return CheckResult("reviewer_independence_sufficient", "not_evaluated",
                           "independence was not declared", undeclared)
    strict = Profile(name=rules.name, minimum_independence=minimum,
                     disclose_independence_below=rules.disclose_independence_below)
    insufficient = [rid for rid, status in statuses if not strict.accepts_independence(status)]
    if insufficient:
        return CheckResult(
            "reviewer_independence_sufficient", "failed",
            f"independence is below the bar set by profile {rules.name!r} "
            f"(minimum: {minimum})", insufficient)
    weak = [rid for rid, status in statuses if strict.must_disclose_independence(status)]
    return CheckResult("reviewer_independence_sufficient", "passed",
                       f"accepted but below {rules.disclose_independence_below} — must be "
                       f"disclosed in the report" if weak else "meets the profile's bar",
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


def evidence_page(ctx: RunContext, ev: dict[str, Any]) -> int | None:
    """Which page of the DOCUMENT this evidence sits on, per the manifest the CLI wrote.

    Deliberately not `locator["page"]`: the locator is written by the agent, and a gate that reads
    the agent's own page number is asking the subject where it was standing. A text span is located
    by walking the manifest's `page_map`; a visual region by matching its render digest.

    Returns None for content with no page at all — Markdown has an empty `page_map` and no pages,
    which is not a failure to locate, it is a document without pages.
    """
    doc = ctx.documents.get(ev.get("document_id", ""))
    if not doc:
        return None
    locator = ev.get("locator") or {}
    if locator.get("type") == "visual_region":
        digest = locator.get("render_sha256")
        for page in doc.get("pages", []):
            if (page.get("render") or {}).get("sha256") == digest:
                return int(page["page_number"])
        return None
    start = locator.get("start_offset")
    if start is None:
        return None
    for span in doc.get("page_map", []):
        if int(span["start_offset"]) <= int(start) < int(span["end_offset"]):
            return int(span["page_number"])
    return None


def _human_verifications(ctx: RunContext, amendment_type: str) -> dict[str, str]:
    """target_artifact_id -> target_artifact_hash, for amendments of one type.

    The hash matters: an amendment verifying an OLD version of an evidence record must not clear
    the gate for a record that has since been re-stamped. Without it, "a human checked this" could
    outlive the thing they checked.
    """
    return {a["target_artifact_id"]: a.get("target_artifact_hash", "")
            for a in _amendments(ctx)
            if a.get("amendment_type") == amendment_type and a.get("target_artifact_id")}


def _unverified(ctx: RunContext, candidates: list[dict[str, Any]],
                amendment_type: str) -> tuple[list[str], list[str]]:
    """Split candidates into (never verified, verified against a different version)."""
    verifications = _human_verifications(ctx, amendment_type)
    missing: list[str] = []
    stale: list[str] = []
    for ev in candidates:
        eid = ev["evidence_id"]
        if eid not in verifications:
            missing.append(eid)
        elif verifications[eid] != ev.get("artifact_hash"):
            stale.append(eid)
    return missing, stale


def check_methodology_assessed(ctx: RunContext) -> CheckResult:
    """A profile may require the methodology review to have considered specific things.

    `medicine.yaml` has asked for `require_sample_size`, `require_controls` and
    `require_preregistration_check` since it was written, and nothing read them — the key was
    declared unimplemented with the reason that judging study design is the agent's job.

    That reason still holds, and this does not judge anything. It checks that the review RECORDED an
    assessment for each required item. "Was this considered?" is answerable deterministically; "was
    it considered well?" is not, and pretending otherwise would be the overreach the whole project
    is built to avoid.
    """
    name = "methodology_items_assessed"
    required = ctx.rules.required_methodology_items
    if not required:
        return CheckResult(name, "not_applicable",
                           f"profile {ctx.rules.name!r} requires no specific methodology item")
    reviews = [r for r in ctx.reviews if r["review_type"] == "methodology_review"]
    if not reviews:
        return CheckResult(name, "not_evaluated", "no methodology review was produced")

    recorded: dict[str, str] = {}
    for review in reviews:
        for item, verdict in (review.get("methodology_assessments") or {}).items():
            recorded[item] = verdict

    missing = [item for item in required if recorded.get(item) not in
               ("assessed", "not_applicable")]
    if missing:
        return CheckResult(name, "not_evaluated",
                           f"profile {ctx.rules.name!r} requires these to be assessed and the "
                           f"methodology review does not record them: {sorted(missing)}")
    return CheckResult(name, "passed",
                       f"{len(required)} required methodology item(s) assessed")


def _declared_extraction_status(ev: dict[str, Any]) -> ExtractionStatus | None:
    """The evidence's own `extraction_status`, as the package's vocabulary, or None if unknown.

    A value outside the enum returns None and is treated as unreliable by the caller — an agent
    writing a word this build does not know has not thereby declared its evidence readable.
    """
    try:
        return ExtractionStatus(str(ev.get("extraction_status", "")))
    except ValueError:
        return None


def check_ocr_evidence(ctx: RunContext) -> CheckResult:
    """Evidence the package considers unreliably extracted needs a human before it backs a claim.

    THE GATE USED TO ASK THE AGENT. It selected candidates purely by `extraction_status` on the
    agent-authored Evidence artifact, so writing `extracted` on evidence taken from a scanned page
    cleared it — while the deterministic record of which pages need OCR sat unread in the Document
    manifest the CLI itself produced. Both are consulted now, and the manifest can only ever add.

    AND IT ASKED ABOUT ONE STATUS OUT OF SEVEN. `== "ocr_required"` is a one-member slice of an enum
    the package already models completely: `ExtractionStatus.needs_human_review` names four members,
    and `Evidence.human_review_required` — a *required* field in the schema — was read by nothing in
    this package at all. So evidence labelled `ambiguous`, `partially_extracted` or
    `human_review_required`, or carrying `human_review_required: true` in the field the schema
    provides for exactly that purpose, returned `not_applicable` and published.

    The asymmetry is what made it bad rather than merely incomplete: the flattering label
    (`extracted`) was correctly distrusted and overridden from the manifest, while the
    self-incriminating labels were discarded. An agent that wrote down the truth about its own
    extraction got the same green verdict as one that did not.

    Both are now collected. OCR keeps its own bucket because it has a deterministic cross-check and
    its own amendment type; the rest are unreliable-by-declaration, and a declaration that a human
    is needed is honoured as one.
    """
    name = "ocr_evidence_human_verified"
    ocr: list[dict[str, Any]] = []
    unreliable: list[dict[str, Any]] = []
    for ev in ctx.evidence:
        doc = ctx.documents.get(ev.get("document_id", ""))
        page = evidence_page(ctx, ev)
        from_manifest = (doc is not None and page is not None
                         and page in set(doc.get("ocr_required_pages") or []))
        declared = _declared_extraction_status(ev)
        if declared is ExtractionStatus.OCR_REQUIRED or from_manifest:
            ocr.append(ev)
        elif declared is None or declared.needs_human_review or ev.get("human_review_required"):
            unreliable.append(ev)

    if not ocr and not unreliable:
        return CheckResult(name, "not_applicable",
                           "no evidence depends on an ocr_required page or declares an "
                           "extraction that needs a human")

    problems: list[str] = []
    flagged: list[str] = []
    forces_review = ctx.rules.forces_human_review("evidence_depends_on_ocr_required_page")

    if ocr:
        missing, stale = _unverified(ctx, ocr, "human_ocr_verification")
        if missing:
            problems.append(f"{len(missing)} on an ocr_required page without a recorded human "
                            f"verification amendment")
        if stale:
            problems.append(f"{len(stale)} verified against a different version of the evidence")
        flagged += missing + stale

    if unreliable:
        # Either human verification type clears these: the point is that a person looked and signed
        # the record, not which of the two amendment names they used.
        verified = set(_human_verifications(ctx, "human_ocr_verification")) | set(
            _human_verifications(ctx, "human_visual_verification"))
        unsigned = [e["evidence_id"] for e in unreliable if e["evidence_id"] not in verified]
        if unsigned:
            statuses = sorted({str(e.get("extraction_status")) for e in unreliable})
            problems.append(f"{len(unsigned)} declare an extraction that needs a human "
                            f"({', '.join(statuses)}) with no verification recorded")
            flagged += unsigned

    if problems:
        return CheckResult(name, "failed",
                           f"{len(ocr) + len(unreliable)} evidence record(s) need a human: "
                           + "; ".join(problems), flagged, human_review=forces_review)
    return CheckResult(name, "passed", f"{len(ocr) + len(unreliable)} verified")


def check_visual_certainty(ctx: RunContext) -> CheckResult:
    """An uncertain visual reading needs a human.

    `interpretation_status` is self-reported in exactly the shape the OCR gate used to be, and
    there is no deterministic record to cross-check it against — the CLI cannot know whether an
    agent read a figure correctly. What IS enforced now: a verification must name the evidence AND
    the version of it that was checked.
    """
    name = "visual_interpretation_certain"
    uncertain = [e for e in ctx.evidence
                 if e.get("interpretation_status") in ("uncertain", "human_review_required")]
    if not uncertain:
        return CheckResult(name, "passed", "no uncertain readings")

    missing, stale = _unverified(ctx, uncertain, "human_visual_verification")
    if missing or stale:
        parts = []
        if missing:
            parts.append(f"{len(missing)} unverified")
        if stale:
            parts.append(f"{len(stale)} verified against a different version")
        return CheckResult(name, "failed",
                           f"{len(uncertain)} uncertain visual reading(s): " + "; ".join(parts),
                           missing + stale,
                           human_review=ctx.rules.forces_human_review(
                               "uncertain_visual_interpretation"))
    return CheckResult(name, "passed", "all verified by a human")


def check_contradictions_disclosed(ctx: RunContext) -> CheckResult:
    """Unresolved contradictions block — and so does never having looked.

    This asked only whether any claim was marked `unresolved`. A run whose every claim said
    `not_checked` therefore returned **passed, "none unresolved"** — the check reporting a clean
    bill of health for a question nobody asked. `not_checked` is a value in the schema enum and the
    initial state of a claim, so this was not a hypothetical.
    """
    unchecked = [c["claim_id"] for c in ctx.claims
                 if c.get("contradiction_status") in (None, "not_checked")]
    if unchecked:
        return CheckResult("contradictions_disclosed", "not_evaluated",
                           f"{len(unchecked)} claim(s) were never checked for contradictions, so "
                           f"whether any exist is unknown — 'none found' and 'nobody looked' are "
                           f"not the same answer", unchecked)
    unresolved = [c["claim_id"] for c in ctx.claims
                  if c.get("contradiction_status") == "unresolved"]
    if not unresolved:
        return CheckResult("contradictions_disclosed", "passed",
                           f"{len(ctx.claims)} claim(s) checked, none unresolved")
    return CheckResult("contradictions_disclosed", "failed",
                       f"{len(unresolved)} claim(s) carry an unresolved contradiction; these must "
                       f"be disclosed and human-reviewed before publication", unresolved,
                       human_review=ctx.rules.forces_human_review(
                           "unresolved_contradiction_on_material_claim"))


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
    # SPEC §26's causal trigger, which nothing could fire.
    #
    # `causal_claim_from_correlational_evidence` sat in `KNOWN_TRIGGERS`, and both shipped profiles
    # asked for it, but no check ever passed that string to `forces_human_review` — so a profile
    # requesting human review for a causal reading drawn from non-causal evidence received nothing,
    # and `research validate` said so in green. The detection already existed in
    # `reporting.language`; it ran only at report time, after the gate it should have informed.
    #
    # It is raised as human review rather than as a failure because the wording check is lexical,
    # not comprehension: it is qualified to say "a person should look at this", never "this is
    # wrong". A profile that does not name the trigger still gets nothing, deliberately.
    causal = [o for o in scan_claims(ctx.claims)
              if o.kind == "causal_language_on_a_non_causal_claim"]
    causal_review = bool(causal) and ctx.rules.forces_human_review(
        "causal_claim_from_correlational_evidence")

    if problems:
        return CheckResult("support_classifications_earned", "failed", "; ".join(problems[:5]),
                           human_review=causal_review)
    if causal_review:
        return CheckResult(
            "support_classifications_earned", "passed",
            f"{len(ctx.claims)} claim(s); {len(causal)} carry causal wording on a claim type that "
            f"is not `causal_claim`, which this profile makes a human-review trigger",
            sorted({o.claim_id for o in causal}), human_review=True)
    return CheckResult("support_classifications_earned", "passed", f"{len(ctx.claims)} claim(s)")


# Relationships that make two documents NOT independent sources of the same fact.
DEPENDENT_RELATIONSHIPS = {
    "duplicate", "republication", "revision_of", "translation_of", "summarizes",
    "derived_from", "shares_primary_dataset", "shares_experimental_result",
}

# The only relationship that ESTABLISHES independence. Everything else — including `unknown` and
# `cites` — leaves it unassessed, which blocks.
#
# There used to be no such value at all, and the check passed on anything outside
# DEPENDENT_RELATIONSHIPS. So `unknown` cleared the gate that recording nothing correctly blocked:
# the same claim ("we did not assess this") passed or blocked depending on whether it was written
# down. `cites` is not independence either — a source that cites another may be repeating it, which
# is exactly the failure spec §24 is about.
INDEPENDENCE_ESTABLISHING = {"independent"}


def check_source_independence(ctx: RunContext) -> CheckResult:
    """Spec §24: multiple documents are not automatically multiple independent sources.

    This is the mistake that makes a single study look like a literature. A finding republished as
    an industry brief, a preprint and its journal version, or three papers reusing one dataset are
    ONE source wearing several hats — and a claim resting on them is not corroborated, merely
    repeated.

    `unknown` independence is never promoted to independent: a multi-source claim whose sources were
    never assessed returns `not_evaluated`, which blocks, rather than passing by default.

    That sentence was in this docstring while the code did the opposite. Independence must now be
    POSITIVELY recorded as `independent`; every other value either establishes dependence (failed)
    or leaves it unassessed (not_evaluated). Absent, `unknown` and `cites` now behave identically,
    because they say the same thing.
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
                if kind is None or kind not in DEPENDENT_RELATIONSHIPS \
                        and kind not in INDEPENDENCE_ESTABLISHING:
                    stated = "never assessed" if kind is None else f"recorded only as {kind!r}"
                    unassessed.append(f"{claim['claim_id']}: independence of {a[:24]}… and "
                                      f"{b[:24]}… was {stated}")
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
                           [u.split(":")[0] for u in unassessed],
                           human_review=ctx.rules.forces_human_review(
                               "source_independence_unestablished"))
    return CheckResult("source_independence_established", "passed",
                       f"{len(needs)} strongly-supported claim(s) rest on independent sources")


def _relationships(ctx: RunContext) -> list[dict[str, Any]]:
    """Read from the context, which loaded them once and kept the load errors."""
    return [r for r in ctx.relationships if r.get("schema_name") == "SourceRelationship"]


# A run has to have reached this before a verdict about it means anything: every stage that
# produces evidence, claims and reviews sits below it.
PUBLISHABLE_FROM = Phase.INDEPENDENTLY_REVIEWED


def check_run_progressed(ctx: RunContext) -> CheckResult:
    """The run must have walked the workflow, not merely accumulated files in the right folders.

    Direct writes into `evidence/` and `claims/` still work — that is a legitimate way to build a
    run — but a run that never advanced a phase has no event log to audit, so nothing recorded WHEN
    each stage was accepted or in what order. `research validate --stage <stage>` is what advances
    it.
    """
    name = "run_reached_a_publishable_phase"
    order = list(Phase)
    try:
        current = Phase(str(ctx.manifest.get("phase")))
    except ValueError:
        return CheckResult(name, "not_evaluated",
                           f"the manifest records an unknown phase "
                           f"{ctx.manifest.get('phase')!r}")
    if order.index(current) < order.index(PUBLISHABLE_FROM):
        return CheckResult(
            name, "not_evaluated",
            f"the run is at {current}; publication requires it to have reached "
            f"{PUBLISHABLE_FROM} through `research validate --stage <stage>`, so that when each "
            f"stage was accepted is on the record")

    # HOW FAR IT GOT IS NOT WHETHER IT MAY GO ON.
    #
    # The disposition was consulted by nothing in validation, so a run parked at
    # `human_review_required` or `validation_failed` could have every check pass and be written to
    # disk as `report_eligible: true` — while the lifecycle refused to advance it, `research status`
    # reported it blocked, and `research report` published it anyway from the stored boolean. Three
    # components disagreeing about the same run.
    #
    # It was worse than a disagreement: `_record_verdict` then attempted the transition the state
    # machine forbids, and `research validate` exited with an unhandled `LifecycleError` — so the
    # ordinary "fix what was flagged and validate again" loop crashed on any run that had once been
    # flagged.
    try:
        disposition = Disposition(str(ctx.manifest.get("disposition")))
    except ValueError:
        return CheckResult(name, "not_evaluated",
                           f"the manifest records an unknown disposition "
                           f"{ctx.manifest.get('disposition')!r}")
    if not disposition.can_advance:
        return CheckResult(
            name, "failed",
            f"run reached {current}, but its disposition is {disposition}: "
            + ("clearing human review needs a recorded human amendment or review artifact, not "
               "another validation run" if disposition is Disposition.HUMAN_REVIEW_REQUIRED
               else "resolve it before publishing"),
            human_review=disposition is Disposition.HUMAN_REVIEW_REQUIRED)
    return CheckResult(name, "passed", f"run reached {current}")


def check_lifecycle(ctx: RunContext) -> CheckResult:
    """Replay the event log: every recorded transition must have been legal.

    Until stage acceptance existed, `runs.manager.transition()` had no caller in `src/`, so the log
    held nothing but the creation event — which this loop skips — and `is_valid_transition` had
    never once been called on a real run. The check reported "event log replays cleanly" about a
    log with nothing in it to replay.

    The manifest is cross-checked against the log for the same reason: `phase` is a field, and a
    manifest claiming `published` above a one-line log used to pass.
    """
    path = safe_join(ctx.ws.root, "runs", ctx.run_id) / "events.jsonl"
    if not path.is_file():
        return CheckResult("lifecycle_transitions_valid", "not_evaluated", "no event log")
    illegal: list[str] = []
    last_phase: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("event") != "lifecycle_transition":
            continue
        prev, new = event.get("previous_phase"), event.get("new_phase")
        last_phase = new
        if prev == new:
            continue
        ok, reason = is_valid_transition(Phase(prev), Phase(new),
                                         Disposition(event.get("previous_disposition", "active")))
        if not ok:
            illegal.append(f"{prev} -> {new}: {reason}")
    if illegal:
        return CheckResult("lifecycle_transitions_valid", "failed", "; ".join(illegal[:5]))

    recorded = ctx.manifest.get("phase")
    if last_phase is None:
        return CheckResult("lifecycle_transitions_valid", "not_evaluated",
                           "the event log records no lifecycle transition, so the manifest's "
                           "phase rests on nothing")
    if recorded != last_phase:
        return CheckResult("lifecycle_transitions_valid", "failed",
                           f"the manifest says phase {recorded!r} but the event log ends at "
                           f"{last_phase!r}; the state and its history disagree")
    return CheckResult("lifecycle_transitions_valid", "passed",
                       f"event log replays cleanly and ends at {last_phase!r}")


def _amendments(ctx: RunContext) -> list[dict[str, Any]]:
    """Only real Amendment artifacts clear a human-verification gate.

    This was unfiltered, and amendments were absent from `check_artifacts_conform`, so nothing ever
    ran `validate_artifact` on one. A two-key JSON object in `amendments/` therefore cleared the OCR
    and visual gates — the schema has always required `target_artifact_hash`, `changed_fields`,
    `reason` and `human`, and nothing checked any of it.
    """
    return [a for a in ctx.amendments if a.get("schema_name") == "Amendment"]


CHECKS = [
    check_profile_loaded,
    check_artifacts_conform,
    check_source_hashes,
    check_derived_text_hashes,
    check_retrieval_provenance,
    check_evidence_references,
    check_text_locators,
    check_visual_locators,
    check_claims_have_evidence,
    check_citation_support,
    lambda ctx: _review_check(ctx, "contradiction_review"),
    lambda ctx: _review_check(ctx, "citation_review"),
    lambda ctx: _review_check(ctx, "methodology_review"),
    lambda ctx: _review_check(ctx, "independent_review"),
    check_run_progressed,
    check_profile_confidence_permitted,
    check_methodology_assessed,
    check_independence,
    check_independence_attested,
    check_ocr_evidence,
    check_visual_certainty,
    check_contradictions_disclosed,
    check_support_classifications,
    check_source_independence,
    check_lifecycle,
]


def validated_inputs(ctx: RunContext) -> dict[str, Any]:
    """Name every artifact this verdict was computed over.

    `report_eligible` was a boolean bound to nothing. `render_report` gates on the stored value and
    then re-reads `claims/` and `evidence/` fresh from disk, so a claim written after `validate` was
    published having never been validated — and one deleted after `validate` vanished from a report
    that still claimed to rest on it.

    The roster is content-derived and order-independent: sorted `(artifact_id, artifact_hash)` pairs
    plus the load-error count, digested into `inputs_hash`. Re-running `build_context` at report
    time and comparing digests answers "are these the artifacts that were judged?" exactly, and the
    pair list makes the answer legible — added, removed, or re-stamped, by id.
    """
    artifacts = [*ctx.evidence, *ctx.claims, *ctx.reviews, *ctx.review_contexts,
                 *ctx.relationships, *ctx.amendments, *ctx.retrieval]
    if ctx.plan:
        artifacts.append(ctx.plan)
    roster = sorted({(str(a.get("artifact_id")), str(a.get("artifact_hash"))) for a in artifacts})
    body = {
        "artifacts": [{"artifact_id": i, "artifact_hash": h} for i, h in roster],
        "load_error_count": len(ctx.load_errors),
    }
    body["inputs_hash"] = sha256_text(canonical_json(body))
    return body


def compare_inputs(recorded: dict[str, Any] | None,
                   current: dict[str, Any]) -> list[str]:
    """Differences between the artifacts a verdict was computed over and the ones on disk now."""
    if not recorded:
        return ["the validation result records no artifact roster, so what it judged is unknown"]
    if recorded.get("inputs_hash") == current["inputs_hash"]:
        return []

    was = {a["artifact_id"]: a["artifact_hash"] for a in recorded.get("artifacts", [])}
    now = {a["artifact_id"]: a["artifact_hash"] for a in current["artifacts"]}
    diffs = [f"added since validation: {aid}" for aid in sorted(set(now) - set(was))]
    diffs += [f"removed since validation: {aid}" for aid in sorted(set(was) - set(now))]
    diffs += [f"re-stamped since validation: {aid}" for aid in sorted(set(was) & set(now))
              if was[aid] != now[aid]]
    if recorded.get("load_error_count") != current["load_error_count"]:
        diffs.append(f"load errors changed: {recorded.get('load_error_count')} -> "
                     f"{current['load_error_count']}")
    return diffs or ["the artifact roster digest changed"]


def _record_verdict(ws: Workspace, run_id: str, *, report_eligible: bool,
                    human_review_required: bool, result_hash: str) -> str:
    """Move the run to match the verdict, where the state machine allows it.

    Transitions are one-step and enforced, so this can only advance a run that actually reached
    `independently_reviewed` — which `check_run_progressed` is what requires. A run built by direct
    writes stays where it is and is told so, rather than being silently promoted.
    """
    from ..runs.manager import transition

    manifest = load_run(ws, run_id)
    current = Phase(manifest["phase"])
    if not report_eligible:
        if Disposition(manifest["disposition"]) is not Disposition.VALIDATION_FAILED:
            transition(ws, run_id, to_disposition=(
                Disposition.HUMAN_REVIEW_REQUIRED if human_review_required
                else Disposition.VALIDATION_FAILED),
                triggered_by="research validate", reason="validation did not clear the gates",
                validation_result=result_hash)
        return "recorded as not eligible"

    if current is not Phase.INDEPENDENTLY_REVIEWED:
        return f"left at {current}: the lifecycle only advances a run that walked the stages"

    # NEVER RAISE OUT OF VALIDATION. The verdict artifact is already on disk by the time this runs,
    # so an exception here leaves a recorded result and a non-zero exit with no explanation of the
    # relationship between them. `check_run_progressed` now blocks a run whose disposition forbids
    # advancing, so an eligible run should always be able to move — but "should" is not a guarantee
    # worth crashing a command over, and the state machine is the authority on its own rules.
    try:
        transition(ws, run_id, to_phase=Phase.VALIDATION_PASSED,
                   to_disposition=Disposition.ACTIVE,
                   triggered_by="research validate", reason="every gate cleared",
                   validation_result=result_hash)
        transition(ws, run_id, to_phase=Phase.REPORT_ELIGIBLE,
                   triggered_by="research validate", reason="report eligibility established",
                   validation_result=result_hash)
    except LifecycleError as exc:
        return f"left at {current}: the lifecycle refused to advance it — {exc.message}"
    return f"advanced to {Phase.REPORT_ELIGIBLE}"


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
        "validated_inputs": validated_inputs(ctx),
    }
    body.pop("validated_at")
    artifact = make_artifact(schema_name="ValidationResult", artifact_id=run_id, body=body,
                             actor_type="cli")
    path = safe_join(ws.root, "runs", run_id, "validation", "validation-result.json")
    write_artifact(path, artifact, root=ws.root)

    # RECORD THE VERDICT IN THE LIFECYCLE.
    #
    # `Phase.VALIDATION_PASSED`, `Phase.REPORT_ELIGIBLE` and `Disposition.VALIDATION_FAILED` existed
    # and were never once set, so `research status` computed `report_eligible` from a phase nothing
    # could reach and answered False for every run — including runs this function had just called
    # eligible. Two commands disagreeing about the central question of the system.
    lifecycle_note = _record_verdict(ws, run_id, report_eligible=report_eligible,
                                     human_review_required=human_review_required,
                                     result_hash=artifact["artifact_hash"])

    return {
        "run_id": run_id,
        "report_eligible": report_eligible,
        "lifecycle": lifecycle_note,
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
