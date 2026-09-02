"""Evidence Verifier — the third real agent in FinGuard AI, distinct from the Critic
(ROADMAP.md §19).

The Critic Agent (backend/critic_agent.py) asks "is there enough evidence backing this
category?" — a check on FinGuard's own deterministic data, run BEFORE the LLM writes anything.

This agent asks a different question, AFTER the LLM has written something: "does this specific
claim the LLM made actually match a real number in the data it was given, or did it drift/
invent/misstate a figure?" That's a real, distinct check — a hallucination guard on the one LLM
call in this codebase, not a duplicate of the Critic's evidence-sufficiency check.

Deliberately simple and deterministic (regex + numeric matching), not a second LLM call judging
the first one's output — that would just create the same infinite-regress problem the Critic's
own docstring already rules out. Every FACT or MODEL PREDICTION claim should cite a real number;
this checks that the number genuinely appears (within a small rounding tolerance) in the exact
input data the Report Agent was given, not somewhere the LLM might have invented or misremembered
from its own training data.

AI INTERPRETATION claims are exempt by definition — they're framing/judgment, not evidence
claims, so there's nothing to verify them against.
"""
import re

# Deliberately narrow: only decimal figures (21.8, 24.02) and percentages (59%, 100%) — the shape
# every real metric in this domain takes (FRI, market_risk, probabilities, confidence). Bare
# integers are excluded on purpose: dates ("2026-07-10"), day counts, and ASCII-hyphen date
# separators otherwise get misread as negative numbers (a literal "-07" from "2026-07-10"), which
# caused a real false positive here during testing — a date claim was flagged UNSUPPORTED because
# the LLM's own date formatting used a different hyphen character than the source data's ISO
# dates, and the ASCII hyphen in the source got parsed as a minus sign. Restricting to figures
# that are actually decimal or percentage-shaped avoids that whole class of false positive.
_NUMBER_RE = re.compile(r"\d+\.\d+%?|\d+%")
_TOLERANCE = 0.6  # allows for LLM rounding (e.g. "roughly 60%" for 59.29%)


def _extract_numbers(text: str) -> list[float]:
    return [float(m.rstrip("%")) for m in _NUMBER_RE.findall(text)]


def verify_claims(labeled_claims: list[dict], input_data: str) -> list[dict]:
    """Checks each FACT/MODEL PREDICTION claim's cited numbers against the real input data the
    Report Agent was given. Returns one verdict per claim; AI INTERPRETATION claims are marked
    NOT_APPLICABLE since they're not evidence claims to begin with.
    """
    source_numbers = _extract_numbers(input_data)
    results = []

    for claim in labeled_claims:
        label = claim.get("label")
        text = claim.get("text", "")

        if label == "AI INTERPRETATION":
            results.append({**claim, "verification": "NOT_APPLICABLE", "verification_detail": "Interpretation, not an evidence claim"})
            continue

        claim_numbers = _extract_numbers(text)
        if not claim_numbers:
            results.append({**claim, "verification": "SUPPORTED", "verification_detail": "No specific figures to verify"})
            continue

        unsupported = []
        for n in claim_numbers:
            if not any(abs(n - s) <= _TOLERANCE for s in source_numbers):
                unsupported.append(n)

        if unsupported:
            results.append({
                **claim,
                "verification": "UNSUPPORTED",
                "verification_detail": f"Figure(s) {unsupported} do not match any value in the source data given to the LLM",
            })
        else:
            results.append({**claim, "verification": "SUPPORTED", "verification_detail": "All cited figures match the source data"})

    return results


def summarize(verified_claims: list[dict]) -> dict:
    unsupported = [c for c in verified_claims if c["verification"] == "UNSUPPORTED"]
    return {
        "verdict": "CLEAN" if not unsupported else "UNSUPPORTED_CLAIMS_FOUND",
        "unsupported_count": len(unsupported),
        "total_checked": sum(1 for c in verified_claims if c["verification"] != "NOT_APPLICABLE"),
    }
