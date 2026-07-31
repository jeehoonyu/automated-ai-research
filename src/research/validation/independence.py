"""Detecting a leak into an "independent" review.

WHY THIS EXISTS. The Claude Code conformance run recorded a defect that no check could see: the
primary agent's first independent-review packet contained the line *"submitted with support
classification: conflicting_evidence"*. That is `primary_confidence`, an explicitly excluded input.
The leak was caught by the author noticing, not by the platform — and the resulting review would
have declared `confirmed_independent` and passed every gate.

`reviewer_independence_sufficient` reads a boolean the host wrote about itself. Every other gate in
this system decides by inspecting something. This module is what it inspects: the actual text the
host says it handed the reviewer, recorded as a `ReviewContext` artifact and scanned against
material drawn from *this run's own artifacts*.

WHAT IT CANNOT DO. It checks what the host **says** it sent. A host that sends a leaky context and
attests a clean one defeats it completely, and no local artifact can prevent that. The improvement
is narrow and worth stating exactly: an accidental leak becomes detectable, and a deliberate one now
requires falsifying a hashed record rather than merely omitting one. That is the difference between
no evidence and falsifiable evidence — not between untrusted and trusted.

FALSE POSITIVES ARE THE REAL RISK. A check that fires on legitimate context gets switched off, and a
switched-off check is worse than none because the docs still list it. So every rule here is
deliberately narrow, and what each rule cannot catch is written down next to it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

# Imported, not restated. The scanner and the contract it enforces must name the same fields, and a
# copy here would drift the moment one of them changed — the exact failure mode catalogued in
# docs/lessons-carried-forward.md §4.
from ..artifacts.registry import schema_enum  # noqa: E402
from ..runs.packets import GRADING_FIELDS, INDEPENDENCE_EXCLUSIONS  # noqa: E402

# Read from the shipped Claim schema rather than typed out again. This was a seven-element tuple
# copied by hand; a classification added to the schema and not added here would simply stop being
# recognised as a leaked grade, and the leak scanner would report a clean context.
SUPPORT_CLASSIFICATIONS = tuple(sorted(schema_enum("Claim", "support_classification")))

# Field names that carry excluded material. Matched only in `key:` / `key =` position — never as a
# bare word, because the work packet legitimately *lists* these names in `excluded_inputs`, and the
# packet is often part of the context. Flagging the contract that forbids the leak would be absurd.
FORBIDDEN_KEYS = (*INDEPENDENCE_EXCLUSIONS, "reasoning_trace", *GRADING_FIELDS)

# Reviews whose conclusions must not reach the independent reviewer (`previous_review_conclusions`).
#
# Derived by SUBTRACTION from the schema rather than listed, so a review type added later is
# excluded by default. Listing three of the five members by hand left `human_review` out: a human
# reviewer's conclusions are exactly the kind of prior judgement an independent reviewer is supposed
# not to see, and the scanner walked straight past them. Only the independent review itself is
# exempt, for the obvious reason.
PRIOR_REVIEW_TYPES = tuple(sorted(schema_enum("Review", "review_type") - {"independent_review"}))

# Prior-review text is compared by n-gram containment. Eight tokens is long enough that a match is
# not coincidence and short enough to survive light rewording. A conclusion shorter than eight
# tokens is NOT detectable this way — a terse "citation does not support the claim" would slip
# through, and that is a real gap, not an oversight.
NGRAM = 8

_GRADE_LABEL = re.compile(
    r"(support[\s_-]*classification|support[\s_-]*level|classified\s+as|classification"
    r"|primary[\s_-]*confidence|primary[\s_-]*rationale)"
    r"[\"'`\s]*[:=]?[\"'`\s]*"
    r"(" + "|".join(SUPPORT_CLASSIFICATIONS) + r")\b",
    re.IGNORECASE,
)

_FORBIDDEN_KEY = re.compile(
    r"[\"'`]?\b(" + "|".join(FORBIDDEN_KEYS) + r")\b[\"'`]?\s*[:=]",
    re.IGNORECASE,
)

_WORD = re.compile(r"[a-z0-9]+")

# A work packet that *explains* each exclusion writes the forbidden names in key position:
#
#     Excluded inputs for this stage:
#       - primary_rationale: the primary agent's reasoning
#       - primary_confidence: how confident the primary agent was
#
# Flagging the contract that forbids the leak would fire on every honest host that pastes the
# packet, and a check that fires on correct behaviour gets switched off — which is worse than no
# check, because the documentation goes on listing it. So rule 2 ignores a name that sits under
# prohibition language.
#
# The exemption is scoped by LINE, not by a character window: the match's own line, plus the nearest
# preceding line that is not itself a list item — which is exactly the heading a bulleted exclusion
# list hangs from. A character window either misses the heading (lists are long) or reaches so far
# back that any leak following a packet is silently forgiven.
#
# It is still a bypass — writing "do not consider that primary_confidence: …" suppresses rule 2.
# That costs little, because rule 1 has no exemption and catches a leaked *grade* regardless of what
# precedes it, and because the threat model already concedes a host willing to attest a clean
# context it did not send. What the exemption protects is the accidental case, which is the case
# this catches at all.
_PROHIBITION = re.compile(
    r"(exclud|forbidden|prohibit|must\s+not|may\s+not|do\s+not|never\s+(?:supply|include|provide))",
    re.IGNORECASE)
_LIST_ITEM = re.compile(r"^\s*([-*•+]|\d+[.)]|[\"'`{\[])")
_MAX_LOOKBACK_LINES = 12


@dataclass(frozen=True)
class Leak:
    """One piece of excluded material found in an attested review context."""

    rule: str
    excerpt: str
    source: str = ""

    def describe(self) -> str:
        where = f" (from {self.source})" if self.source else ""
        return f"{self.rule}: {self.excerpt!r}{where}"


def _tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _ngrams(tokens: list[str], n: int = NGRAM) -> set[tuple[str, ...]]:
    return {tuple(tokens[i:i + n]) for i in range(len(tokens) - n + 1)}


def _excerpt(text: str, start: int, end: int, pad: int = 40) -> str:
    lo, hi = max(0, start - pad), min(len(text), end + pad)
    return " ".join(text[lo:hi].split())


def _under_prohibition(context: str, offset: int) -> bool:
    """Is the match at `offset` part of a contract restating its own exclusions?

    Looks at the match's line plus the nearest preceding line that is not itself a list item — the
    heading a bulleted exclusion list hangs from.
    """
    line_no = context.count("\n", 0, offset)
    lines = context.split("\n")
    window = [lines[line_no]]
    for index in range(line_no - 1, max(-1, line_no - 1 - _MAX_LOOKBACK_LINES), -1):
        line = lines[index]
        if not line.strip():
            continue
        window.append(line)
        if not _LIST_ITEM.match(line):
            break
    return bool(_PROHIBITION.search("\n".join(window)))


def prior_review_conclusions(reviews: Iterable[dict[str, Any]]) -> list[tuple[str, str]]:
    """(review_id, conclusion text) for every review that ran before the independent one.

    Only *conclusions* are collected. A prior review's list of which artifacts it looked at is not a
    conclusion, and treating it as one would flag any context that names the same evidence — which
    the independent reviewer is explicitly allowed to see.
    """
    out: list[tuple[str, str]] = []
    for review in reviews:
        if review.get("review_type") not in PRIOR_REVIEW_TYPES:
            continue
        rid = str(review.get("review_id", "?"))
        parts: list[str] = []
        for key in ("findings", "blocking_issues", "warnings", "required_amendments"):
            parts.extend(str(v) for v in (review.get(key) or []))
        for entry in review.get("per_claim") or []:
            parts.extend(str(entry.get(k, "")) for k in ("assessment", "notes") if entry.get(k))
        for part in parts:
            if part.strip():
                out.append((rid, part))
    return out


def scan_context(context: str, *, reviews: Iterable[dict[str, Any]] = ()) -> list[Leak]:
    """Find excluded material in the text a host attests it gave the independent reviewer.

    Three rules, narrowest first:

    1. **A labelled grade.** `support classification: conflicting_evidence` — the exact shape of the
       real historical leak, and the shape raw claim JSON takes. Does NOT catch an unlabelled grade:
       the bare word "verified" in a sentence is ordinary English and flagging it would make the
       check unusable.
    2. **An excluded field in key position.** `"primary_rationale": "..."`. Does NOT catch the same
       content pasted as prose with the field name stripped.
    3. **A prior review's conclusion, near-verbatim.** Eight-token containment. Does NOT catch a
       conclusion that was paraphrased, summarised, or is shorter than eight tokens.

    A clean result therefore means "no leak of these three shapes", never "independent".
    """
    leaks: list[Leak] = []

    for match in _GRADE_LABEL.finditer(context):
        leaks.append(Leak(
            "graded_classification_disclosed",
            _excerpt(context, match.start(), match.end()),
            "the primary agent's support_classification is `primary_confidence` (spec §13)"))

    for match in _FORBIDDEN_KEY.finditer(context):
        field_name = match.group(1).lower()
        if _under_prohibition(context, match.start()):
            continue                                    # the contract naming its own exclusions
        if any(leak.rule == "excluded_field_present" and field_name in leak.source
               for leak in leaks):
            continue                                    # one report per field, not per occurrence
        leaks.append(Leak(
            "excluded_field_present",
            _excerpt(context, match.start(), match.end()),
            f"`{field_name}` is an excluded input for this stage"))

    context_ngrams = _ngrams(_tokens(context))
    if context_ngrams:
        for review_id, conclusion in prior_review_conclusions(reviews):
            shared = _ngrams(_tokens(conclusion)) & context_ngrams
            if shared:
                phrase = " ".join(sorted(shared)[0])
                leaks.append(Leak(
                    "prior_review_conclusion_present",
                    phrase,
                    f"{review_id} reached this conclusion before the independent review"))
    return leaks
