"""Report Agent — the first real LLM integration in FinGuard AI.

Per ROADMAP.md's own rules (Rule 13: "LLMs reason and communicate, they do not predict numbers")
and the docs/roadmap.md build order (§40: Report Agent before any orchestration), this is
deliberately the smallest possible agentic step: ONE LLM call, no tools, no planning loop, no
multi-agent hand-off. It takes numbers FinGuard has already computed deterministically (FRI,
trend, forecast probability, taxonomy reasons) and turns them into a short, readable paragraph.

The LLM is the communication layer, not the source of truth (ROADMAP.md §20). Enforced two ways:
1. The prompt hands the model only real, already-computed values — it is never asked to invent a
   score or estimate a probability itself.
2. Every sentence in the returned report is labeled FACT, MODEL PREDICTION, or AI INTERPRETATION
   (ROADMAP.md §21's evidence-first distinction), produced by asking the model to tag its own
   output in a structured format, so a reader can tell "this is a real number" from "this is the
   model's phrasing of it."

Uses Groq (groq.com), model openai/gpt-oss-120b — a free-tier API, chosen specifically because it
costs nothing and needs no paid signup, which was an explicit constraint for this project.
"""
import os
from pathlib import Path

import yaml
from groq import Groq

_API_KEYS_PATH = Path(__file__).resolve().parent.parent / "config" / "api_keys.yaml"

_MODEL = "openai/gpt-oss-120b"

_SYSTEM_PROMPT = """You are a financial risk report writer. You will be given ONLY real,
already-computed data about a stock: a risk score, a historical trend, a model-predicted
probability, and evidence-linked risk factors. Do not invent, estimate, or adjust any number —
use only the numbers given to you, verbatim.

Write a short report (4-6 sentences) explaining the company's current risk situation in plain
language. Then, on separate lines, output 3-5 individual claims from your report, each prefixed
with exactly one of these labels:
FACT: <a claim directly stated by the input data, e.g. a real score or real evidence>
MODEL PREDICTION: <a claim that restates the forecast probability, if one was provided>
AI INTERPRETATION: <your own explanation, judgment, or framing that goes beyond the raw numbers>

Never label your own interpretation as FACT. Never state a probability or score that was not
given to you in the input data."""

_PORTFOLIO_SYSTEM_PROMPT = """You are a portfolio risk report writer. You will be given ONLY
real, already-computed data about a watchlist of stocks: each ticker's FinGuard Risk Index (FRI),
and portfolio-level aggregates (average FRI, highest-risk ticker, sector breakdown if given,
count of tickers with rising risk trend). Do not invent, estimate, or adjust any number — use
only the numbers given to you, verbatim. Do not invent a ticker's score if it was not given.

Write a short portfolio-level report (4-6 sentences) explaining the overall risk picture in plain
language — which tickers stand out, whether risk is concentrated, and the overall trend. Then, on
separate lines, output 3-5 individual claims from your report, each prefixed with exactly one of
these labels:
FACT: <a claim directly stated by the input data, e.g. a real score or aggregate figure>
MODEL PREDICTION: <a claim restating a forecast probability, if one was provided for a ticker>
AI INTERPRETATION: <your own explanation, judgment, or framing that goes beyond the raw numbers>

Never label your own interpretation as FACT. Never state a probability or score that was not
given to you in the input data."""


def _get_client() -> Groq | None:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key and _API_KEYS_PATH.exists():
        with open(_API_KEYS_PATH) as f:
            api_key = (yaml.safe_load(f) or {}).get("groq_api_key") or None
    if not api_key:
        return None
    return Groq(api_key=api_key)


def _build_input_summary(ticker: str, taxonomy: dict, trend: dict | None, forecast: dict | None) -> str:
    fri = taxonomy.get("fri") or {}
    categories = taxonomy.get("categories") or {}

    lines = [f"Ticker: {ticker.upper()}"]
    if fri.get("score") is not None:
        lines.append(f"FinGuard Risk Index (FRI): {fri['score']} / 100, confidence {round(fri.get('confidence', 0) * 100)}%")
    for cat_name, cat in categories.items():
        if cat.get("score") is not None:
            lines.append(f"{cat_name}: {cat['score']}")
            reasons = cat.get("reasons") or []
            for r in reasons[:2]:
                text = r.get("headline") or r.get("label") if isinstance(r, dict) else r
                if text:
                    lines.append(f"  evidence: {text}")

    if trend:
        lines.append(
            f"Historical trend: market_risk went from {trend.get('from_value')} on "
            f"{trend.get('from_date')} to {trend.get('to_value')} on {trend.get('to_date')} "
            f"({trend.get('direction')})."
        )

    if forecast:
        pct = round(forecast["probability_market_risk_increase_10pt"] * 100)
        lines.append(
            f"Forecast model prediction: {pct}% probability that market_risk rises by 10+ "
            f"points over the next {forecast.get('horizon_trading_days', 30)} trading days "
            f"(trained model, test ROC-AUC {forecast.get('model_test_metrics', {}).get('roc_auc')})."
        )

    return "\n".join(lines)


def _parse_response(raw: str) -> tuple[str, list[dict]]:
    labeled_claims = []
    report_lines = []
    for line in raw.splitlines():
        stripped = line.strip()
        matched = False
        for label in ("FACT:", "MODEL PREDICTION:", "AI INTERPRETATION:"):
            if stripped.startswith(label):
                labeled_claims.append({"label": label.rstrip(":"), "text": stripped[len(label):].strip()})
                matched = True
                break
        if not matched and stripped:
            report_lines.append(stripped)
    return "\n".join(report_lines), labeled_claims


def _call_llm(client: Groq, user_content: str, revision_note: str | None = None, system_prompt: str = _SYSTEM_PROMPT) -> str:
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    if revision_note:
        messages.append({
            "role": "user",
            "content": (
                f"A Critic Agent reviewed your report and found these issues with how the "
                f"evidence was framed:\n{revision_note}\n\n"
                f"Revise your report and labeled claims to address these concerns directly — "
                f"add appropriate hedging language where evidence is weak. Do not remove the "
                f"FACT/MODEL PREDICTION/AI INTERPRETATION labeling format."
            ),
        })
    completion = client.chat.completions.create(
        model=_MODEL,
        messages=messages,
        temperature=0.3,
        max_tokens=1500,
        reasoning_effort="low",
    )
    return completion.choices[0].message.content


def generate_report(ticker: str, taxonomy: dict, trend: dict | None, forecast: dict | None) -> dict:
    """Builds the input summary from real FinGuard data and asks the LLM to explain it.

    Raises RuntimeError if no Groq API key is configured — the caller should surface that as a
    503, not silently fall back to a fabricated report.
    """
    client = _get_client()
    if client is None:
        raise RuntimeError("No Groq API key configured (set GROQ_API_KEY or config/api_keys.yaml's groq_api_key)")

    user_content = _build_input_summary(ticker, taxonomy, trend, forecast)
    raw = _call_llm(client, user_content)
    report_text, labeled_claims = _parse_response(raw)

    return {
        "ticker": ticker.upper(),
        "report": report_text,
        "labeled_claims": labeled_claims,
        "input_data": user_content,
        "model": _MODEL,
        "note": (
            f"Generated by a real LLM call (Groq, {_MODEL}) — the only place in FinGuard "
            "that uses generative AI. The LLM was given only already-computed real numbers "
            "(never asked to invent a score) and asked to label each claim FACT / MODEL "
            "PREDICTION / AI INTERPRETATION, per the evidence-first principle: AI framing is "
            "never presented as if it were a measured fact."
        ),
    }


def generate_report_with_critique(
    ticker: str, taxonomy: dict, trend: dict | None, forecast: dict | None
) -> dict:
    """First real agentic feedback loop (ROADMAP.md §18): generates a report, runs it past the
    Critic Agent's deterministic evidence-sufficiency check, and — if the Critic finds real
    issues — sends it back to the LLM for ONE revision pass with the specific concerns attached,
    rather than accepting the first draft unconditionally.
    """
    from critic_agent import critique, MAX_REVISIONS
    from evidence_verifier import verify_claims, summarize as summarize_verification

    client = _get_client()
    if client is None:
        raise RuntimeError("No Groq API key configured (set GROQ_API_KEY or config/api_keys.yaml's groq_api_key)")

    user_content = _build_input_summary(ticker, taxonomy, trend, forecast)
    raw = _call_llm(client, user_content)
    report_text, labeled_claims = _parse_response(raw)

    critic_result = critique(taxonomy, forecast)
    revisions = 0

    while critic_result["verdict"] == "INSUFFICIENT" and revisions < MAX_REVISIONS:
        revision_note = "\n".join(f"- {issue}" for issue in critic_result["issues"])
        raw = _call_llm(client, user_content, revision_note=revision_note)
        report_text, labeled_claims = _parse_response(raw)
        revisions += 1
        critic_result = critique(taxonomy, forecast)

    verified_claims = verify_claims(labeled_claims, user_content)
    verification_summary = summarize_verification(verified_claims)

    return {
        "ticker": ticker.upper(),
        "report": report_text,
        "labeled_claims": verified_claims,
        "input_data": user_content,
        "model": _MODEL,
        "critic": {
            "verdict": critic_result["verdict"],
            "issues": critic_result["issues"],
            "revisions_requested": revisions,
        },
        "evidence_verification": verification_summary,
        "note": (
            f"Generated by a real LLM call (Groq, {_MODEL}), reviewed by a deterministic Critic "
            f"Agent (backend/critic_agent.py) that checks evidence sufficiency (FRI confidence, "
            f"missing evidence, weak forecast performance) and can request ONE revision with "
            f"specific concerns attached — a real feedback loop, not just a single unconditional "
            f"pass. {'The Critic requested a revision.' if revisions else 'The Critic found the evidence sufficient on the first pass.'} "
            "Every claim is then checked by a separate Evidence Verifier Agent "
            "(backend/evidence_verifier.py) that confirms each FACT/MODEL PREDICTION claim's "
            "cited figures genuinely match the real data the LLM was given, catching drift or "
            "invention the Critic's evidence-sufficiency check wouldn't. "
            "Every claim is labeled FACT / MODEL PREDICTION / AI INTERPRETATION; AI framing is "
            "never presented as if it were a measured fact."
        ),
    }


def _build_portfolio_summary(tickers_data: list[dict]) -> str:
    """tickers_data: list of {"ticker", "fri", "confidence", "trend_direction"} for tickers that
    had a real, computable FRI. Aggregates are computed here in Python — real arithmetic, not
    something the LLM is asked to compute or estimate itself."""
    valid = [t for t in tickers_data if t.get("fri") is not None]
    lines = [f"Portfolio of {len(tickers_data)} tickers, {len(valid)} with a computable FRI."]

    if valid:
        avg_fri = round(sum(t["fri"] for t in valid) / len(valid), 1)
        highest = max(valid, key=lambda t: t["fri"])
        rising = [t["ticker"] for t in valid if t.get("trend_direction") == "increasing"]
        lines.append(f"Average FRI across the portfolio: {avg_fri} / 100.")
        lines.append(f"Highest-risk ticker: {highest['ticker']} (FRI {highest['fri']}).")
        lines.append(f"Tickers with a rising risk trend: {', '.join(rising) if rising else 'none'}.")
        lines.append("Per-ticker scores:")
        for t in valid:
            lines.append(f"  {t['ticker']}: FRI {t['fri']} (confidence {round(t.get('confidence', 0) * 100)}%)")

    missing = [t["ticker"] for t in tickers_data if t.get("fri") is None]
    if missing:
        lines.append(f"Tickers with no computable FRI (excluded from aggregates): {', '.join(missing)}.")

    return "\n".join(lines)


def generate_portfolio_report(tickers_data: list[dict]) -> dict:
    """Portfolio-level counterpart to generate_report_with_critique — a real second request type
    for the Orchestrator to route to (ROADMAP.md §33's portfolio intelligence, first cut).
    Aggregates (average FRI, highest-risk ticker, rising-trend count) are computed in Python, not
    by the LLM, per the same "LLM explains, doesn't compute" principle as the single-ticker report.

    Now runs a portfolio-shaped Critic Agent (critic_agent.critique_portfolio) — a distinct check
    from the single-ticker critique(): it asks whether there's enough real coverage ACROSS the
    portfolio (how many tickers actually have data, how confident each one is) to trust an
    aggregate claim, not whether one ticker's categories are individually evidenced. The Evidence
    Verifier is reused as-is afterward, since it only needs claim text + a source string.
    """
    from critic_agent import critique_portfolio, MAX_REVISIONS
    from evidence_verifier import verify_claims, summarize as summarize_verification

    client = _get_client()
    if client is None:
        raise RuntimeError("No Groq API key configured (set GROQ_API_KEY or config/api_keys.yaml's groq_api_key)")

    user_content = _build_portfolio_summary(tickers_data)
    raw = _call_llm(client, user_content, system_prompt=_PORTFOLIO_SYSTEM_PROMPT)
    report_text, labeled_claims = _parse_response(raw)

    critic_result = critique_portfolio(tickers_data)
    revisions = 0

    while critic_result["verdict"] == "INSUFFICIENT" and revisions < MAX_REVISIONS:
        revision_note = "\n".join(f"- {issue}" for issue in critic_result["issues"])
        raw = _call_llm(client, user_content, revision_note=revision_note, system_prompt=_PORTFOLIO_SYSTEM_PROMPT)
        report_text, labeled_claims = _parse_response(raw)
        revisions += 1
        critic_result = critique_portfolio(tickers_data)

    verified_claims = verify_claims(labeled_claims, user_content)
    verification_summary = summarize_verification(verified_claims)

    return {
        "report": report_text,
        "labeled_claims": verified_claims,
        "input_data": user_content,
        "model": _MODEL,
        "critic": {
            "verdict": critic_result["verdict"],
            "issues": critic_result["issues"],
            "revisions_requested": revisions,
        },
        "evidence_verification": verification_summary,
        "note": (
            f"Generated by a real LLM call (Groq, {_MODEL}) over portfolio-level aggregates "
            "computed in Python (not by the LLM). Reviewed by a portfolio-shaped Critic Agent "
            "(checks coverage across the whole portfolio, not one ticker's categories) that can "
            "request one revision, then checked by the same Evidence Verifier Agent used for "
            "single-ticker reports. Every claim is labeled FACT / MODEL PREDICTION / "
            "AI INTERPRETATION."
        ),
    }
