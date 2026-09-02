"""Critic Agent — the first real feedback loop in FinGuard AI (ROADMAP.md §18).

Per the spec: "The system should be able to send the task back to another agent. That creates an
actual feedback loop." This is the smallest honest version of that: a deterministic evidence-
sufficiency check (not another LLM call — the critique criteria are inspectable rules, not a
model's opinion) that can send the Report Agent's output back for ONE revision pass if the
evidence backing it is weak, with a specific, machine-generated reason attached to the request —
not just "try again."

Deliberately narrow, like every other "first cut" in this codebase (the forecast baseline, the
Report Agent itself): checks a handful of concrete, real weaknesses that are already visible in
FinGuard's own data —
  - FRI confidence too low (too little real data backing the score)
  - forecast missing or the underlying model's own measured test performance is weak
  - a taxonomy category cited as evidence has zero real reasons attached
— not a general-purpose "is this good reasoning" judge (which would need another LLM call the
critic would then also need criticism of, an infinite regress this project isn't attempting to
solve). This is a real, if small, instance of the evidence-verification principle in ROADMAP.md
§19: claims should be checked against evidence sufficiency before being presented as final.
"""

CONFIDENCE_THRESHOLD = 0.5
WEAK_MODEL_ROC_AUC = 0.6
MAX_REVISIONS = 1


def critique(taxonomy: dict, forecast: dict | None) -> dict:
    """Returns {"verdict": "SUFFICIENT"|"INSUFFICIENT", "issues": [...]}."""
    issues = []

    fri = taxonomy.get("fri") or {}
    confidence = fri.get("confidence")
    if confidence is not None and confidence < CONFIDENCE_THRESHOLD:
        issues.append(
            f"FRI confidence is only {round(confidence * 100)}% — fewer than half the taxonomy "
            f"categories have real data backing this score. Any overall risk framing should be "
            f"explicitly hedged as low-confidence, not stated plainly."
        )

    categories = taxonomy.get("categories") or {}
    for name, cat in categories.items():
        if cat.get("score") is not None and not cat.get("reasons"):
            issues.append(
                f"{name} has a score ({cat['score']}) but zero cited evidence — a claim about "
                f"this category should not be stated as if it were evidence-backed."
            )

    if forecast is None:
        issues.append(
            "No forecast data available for this ticker — the report must not speculate about "
            "future risk direction beyond the real historical trend."
        )
    else:
        test_metrics = forecast.get("model_test_metrics") or {}
        roc_auc = test_metrics.get("roc_auc")
        if roc_auc is not None and roc_auc < WEAK_MODEL_ROC_AUC:
            issues.append(
                f"The forecast model's own measured test ROC-AUC ({roc_auc}) is weak — the "
                f"forecast probability should be framed as a low-confidence early signal, not a "
                f"reliable prediction."
            )

    return {
        "verdict": "SUFFICIENT" if not issues else "INSUFFICIENT",
        "issues": issues,
    }


PORTFOLIO_MIN_COVERAGE = 0.5
PORTFOLIO_MIN_VALID_COUNT = 2
PORTFOLIO_CONFIDENCE_THRESHOLD = 0.5


def critique_portfolio(tickers_data: list[dict]) -> dict:
    """Portfolio-shaped counterpart to critique() — a real, different check, not a duplicate.
    critique() asks "is there enough evidence behind ONE ticker's categories"; this asks "is
    there enough real coverage across the WHOLE portfolio to trust an aggregate claim like
    'average FRI' or 'highest-risk ticker'" — a distinct kind of insufficiency that only exists
    once you're aggregating across multiple tickers.
    """
    issues = []
    total = len(tickers_data)
    valid = [t for t in tickers_data if t.get("fri") is not None]

    if total == 0:
        return {"verdict": "INSUFFICIENT", "issues": ["No tickers provided."]}

    coverage = len(valid) / total
    if coverage < PORTFOLIO_MIN_COVERAGE:
        issues.append(
            f"Only {len(valid)} of {total} tickers ({round(coverage * 100)}%) have a computable "
            f"FRI — any portfolio-wide average or 'highest-risk' claim should be explicitly "
            f"hedged as based on partial coverage, not the whole watchlist."
        )

    if len(valid) < PORTFOLIO_MIN_VALID_COUNT:
        issues.append(
            f"Only {len(valid)} ticker(s) have real data — an 'average' or portfolio-wide trend "
            f"claim is not meaningful with this few data points and should be avoided or "
            f"heavily qualified."
        )

    confidences = [t.get("confidence") for t in valid if t.get("confidence") is not None]
    if confidences:
        avg_confidence = sum(confidences) / len(confidences)
        if avg_confidence < PORTFOLIO_CONFIDENCE_THRESHOLD:
            issues.append(
                f"Average per-ticker FRI confidence across the portfolio is only "
                f"{round(avg_confidence * 100)}% — the portfolio risk picture itself should be "
                f"framed as low-confidence, not stated plainly."
            )

    return {
        "verdict": "SUFFICIENT" if not issues else "INSUFFICIENT",
        "issues": issues,
    }
