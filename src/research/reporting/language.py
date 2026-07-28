"""Overstatement detection: does a claim's WORDING outrun its validated classification?

SPEC §32: *"The report generator must not strengthen the language of a claim beyond its validated
classification."* That rule is usually read as a constraint on the generator's own prose, and this
renderer satisfies it structurally — it emits claim text verbatim and a label from a fixed table, so
it has no freedom to editorialise.

But that leaves the harder half. The claim TEXT is written by an agent, and a claim reading "this
definitively proves X" carries `weakly_supported` just as happily as one reading "this suggests X".
Rendering it faithfully then publishes an overstatement while every gate reports green — which is
precisely the failure recorded in docs/lessons-carried-forward.md §5, where a script computed a
refutation and printed the opposite.

So the wording is checked against the classification. This is a lexical heuristic, not
comprehension:
it catches the common absolutes and hedges and will miss a subtle one. It is deliberately tuned to
flag for disclosure rather than to silently rewrite — the renderer never edits an agent's words.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Strength tiers. A word from a tier above the claim's classification is an overstatement.
_ABSOLUTE = r"\b(prove[sdn]?|proof|definitively|conclusively|establishes?" \
            r"|demonstrates conclusively|" \
            r"beyond doubt|certainly|undeniably|always|never|all cases|guarantees?|confirms?)\b"
_STRONG = r"\b(shows?|demonstrates?|establishes|clearly|strongly indicates?|significant(?:ly)?|" \
          r"substantial(?:ly)?)\b"
_CAUSAL = r"\b(causes?|caused|causing|because of|due to|leads? to|results? in|drives?)\b"

ABSOLUTE_RE = re.compile(_ABSOLUTE, re.I)
STRONG_RE = re.compile(_STRONG, re.I)
CAUSAL_RE = re.compile(_CAUSAL, re.I)

# What each classification is allowed to sound like.
MAX_STRENGTH: dict[str, str] = {
    "verified": "absolute",
    "strongly_supported": "strong",
    "moderately_supported": "strong",
    "weakly_supported": "hedged",
    "conflicting_evidence": "hedged",
    "unsupported": "hedged",
    "unable_to_determine": "hedged",
}

# Human-readable qualifier the renderer prints next to every claim. Fixed table: the generator
# cannot choose a friendlier phrasing for a weak result.
QUALIFIER: dict[str, str] = {
    "verified": "Verified — directly checkable against the cited source.",
    "strongly_supported": "Strongly supported — multiple reviewed sources agree.",
    "moderately_supported": "Moderately supported — evidence is meaningful but incomplete.",
    "weakly_supported": "Weakly supported — evidence is limited or indirect.",
    "conflicting_evidence": "Conflicting evidence — substantial evidence disagrees.",
    "unsupported": "UNSUPPORTED — the cited evidence does not support this statement.",
    "unable_to_determine": "Unable to determine — the available evidence is insufficient.",
}

CORRELATIONAL_TYPES = {"correlational_claim", "descriptive_result", "comparative_result"}


@dataclass
class Overstatement:
    claim_id: str
    kind: str
    detail: str
    matched: list[str]


def check_claim_language(claim: dict[str, Any]) -> list[Overstatement]:
    """Flag wording that outruns the claim's classification or type."""
    text = str(claim.get("claim", ""))
    cid = str(claim.get("claim_id", "?"))
    classification = str(claim.get("support_classification", ""))
    claim_type = str(claim.get("claim_type", ""))
    allowed = MAX_STRENGTH.get(classification, "hedged")
    out: list[Overstatement] = []

    absolutes = sorted({m.group(0).lower() for m in ABSOLUTE_RE.finditer(text)})
    strong = sorted({m.group(0).lower() for m in STRONG_RE.finditer(text)})

    if absolutes and allowed != "absolute":
        out.append(Overstatement(
            cid, "absolute_language_beyond_classification",
            f"the wording asserts certainty ({', '.join(absolutes)}) but the claim is classified "
            f"{classification}",
            absolutes))
    if strong and allowed == "hedged":
        out.append(Overstatement(
            cid, "assertive_language_beyond_classification",
            f"the wording asserts a demonstrated result ({', '.join(strong)}) but the claim is "
            f"classified {classification}",
            strong))

    # Spec §26: a causal reading drawn from correlational evidence is a human-review trigger.
    causal = sorted({m.group(0).lower() for m in CAUSAL_RE.finditer(text)})
    if causal and claim_type in CORRELATIONAL_TYPES:
        out.append(Overstatement(
            cid, "causal_language_on_a_non_causal_claim",
            f"the wording implies causation ({', '.join(causal)}) but the claim type is "
            f"{claim_type}",
            causal))
    return out


def scan_claims(claims: list[dict[str, Any]]) -> list[Overstatement]:
    return [o for claim in claims for o in check_claim_language(claim)]
