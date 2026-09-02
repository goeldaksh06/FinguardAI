"""Orchestrator/Planner — the first real dynamic routing step (ROADMAP.md §5).

Until now, every FinGuard endpoint called a fixed, hardcoded sequence: taxonomy -> trend ->
forecast -> report -> critic, regardless of what data was actually available for a given ticker.
That's not planning, it's a pipeline. This module makes it a real (if small) planning decision:

  1. Check what data is actually available for this ticker BEFORE deciding what to run — e.g. no
     live price data at all means there's no point calling the taxonomy, trend, or forecast steps
     (they'd all fail or return nothing), so the plan skips straight to reporting that failure.
  2. Run each step that the plan calls for, catching per-step failures individually so one missing
     signal (e.g. no forecast data for a newly-listed ticker) doesn't abort the whole
     investigation — the Report Agent already handles null/missing categories honestly, so a
     partial result is real and usable, not a failure.
  3. Produce a step-by-step trace (ROADMAP.md §32's "live execution trace" concept) recording each
     decision made and why, timestamped — real routing decisions, not a fabricated log dressed up
     to look like one.

Deliberately NOT an LLM-driven planner. The decisions here are simple, inspectable rules ("does
live data exist -> yes/no"), not a model reasoning about intent, because there's exactly one kind
of request this product currently supports (investigate one ticker) — an LLM planner would be
solving a routing problem that doesn't exist yet. Real dynamic planning belongs here once there
are genuinely different request types to route between (e.g. single-ticker vs. portfolio vs.
scenario), per ROADMAP.md §31.
"""
from datetime import datetime, timezone


def _trace_step(agent: str, decision: str, detail: str) -> dict:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": agent,
        "decision": decision,
        "detail": detail,
    }


def run_investigation(
    ticker: str,
    get_indicator_frame,
    build_taxonomy,
    compute_trend,
    compute_forecast,
    generate_report_with_critique,
) -> dict:
    """Plans and executes a full investigation for one ticker. Takes the existing app.py helpers
    as arguments rather than importing them, so this module has no circular import on app.py and
    stays independently testable.
    """
    trace = []
    ticker = ticker.upper()

    trace.append(_trace_step("Orchestrator", "investigation_started", f"Planning investigation for {ticker}"))

    try:
        get_indicator_frame(ticker)
    except Exception as exc:
        trace.append(_trace_step(
            "Orchestrator", "aborted",
            f"No live or cached market data available for {ticker} — cannot proceed with any "
            f"downstream agent ({exc})",
        ))
        return {"ticker": ticker, "status": "aborted", "trace": trace, "result": None}

    trace.append(_trace_step("Market Agent", "data_available", "Live/cached market data confirmed — proceeding"))

    taxonomy = None
    try:
        taxonomy = build_taxonomy(ticker)
        present = [k for k, v in taxonomy["categories"].items() if v.get("score") is not None]
        missing = [k for k, v in taxonomy["categories"].items() if v.get("score") is None]
        trace.append(_trace_step(
            "Risk Analyst Agent", "taxonomy_computed",
            f"FRI {taxonomy['fri']['score']} (confidence {round(taxonomy['fri']['confidence'] * 100)}%). "
            f"Categories with data: {', '.join(present) or 'none'}. Missing: {', '.join(missing) or 'none'}.",
        ))
    except Exception as exc:
        trace.append(_trace_step("Risk Analyst Agent", "failed", f"Taxonomy computation failed: {exc}"))

    trend = None
    try:
        trend = compute_trend(ticker)
        if trend:
            trace.append(_trace_step(
                "History Agent", "trend_computed",
                f"market_risk {trend['direction']}: {trend['from_value']} -> {trend['to_value']} "
                f"over {trend.get('lookback_trading_days', 30)} trading days",
            ))
        else:
            trace.append(_trace_step("History Agent", "skipped", "Not enough live price history for a trend comparison"))
    except Exception as exc:
        trace.append(_trace_step("History Agent", "failed", f"Trend computation failed: {exc}"))

    forecast = None
    try:
        forecast = compute_forecast(ticker)
        if forecast:
            trace.append(_trace_step(
                "Forecast Agent", "forecast_computed",
                f"P(market_risk +10pts / 30d) = {round(forecast['probability_market_risk_increase_10pt'] * 100)}% "
                f"(model test ROC-AUC {forecast.get('model_test_metrics', {}).get('roc_auc')})",
            ))
        else:
            trace.append(_trace_step("Forecast Agent", "skipped", "Forecast model unavailable or insufficient live data"))
    except Exception as exc:
        trace.append(_trace_step("Forecast Agent", "failed", f"Forecast computation failed: {exc}"))

    if taxonomy is None:
        trace.append(_trace_step(
            "Orchestrator", "aborted",
            "No taxonomy available — cannot generate a report with no risk data to explain",
        ))
        return {"ticker": ticker, "status": "aborted", "trace": trace, "result": None}

    try:
        report_result = generate_report_with_critique(ticker, taxonomy, trend, forecast)
        critic = report_result.get("critic") or {}
        trace.append(_trace_step(
            "Report Agent", "report_generated",
            f"Report drafted, {len(report_result.get('labeled_claims', []))} labeled claims",
        ))
        trace.append(_trace_step(
            "Critic Agent", critic.get("verdict", "unknown"),
            f"{len(critic.get('issues', []))} issue(s) found, "
            f"{critic.get('revisions_requested', 0)} revision(s) requested",
        ))
        verification = report_result.get("evidence_verification") or {}
        trace.append(_trace_step(
            "Evidence Verifier", verification.get("verdict", "unknown"),
            f"{verification.get('unsupported_count', 0)} of {verification.get('total_checked', 0)} "
            f"checked claims had figures not traceable to the source data",
        ))
    except RuntimeError as exc:
        trace.append(_trace_step("Report Agent", "failed", str(exc)))
        return {
            "ticker": ticker, "status": "partial", "trace": trace,
            "result": {"taxonomy": taxonomy, "trend": trend, "forecast": forecast, "report": None},
        }

    trace.append(_trace_step("Orchestrator", "investigation_complete", f"Investigation for {ticker} complete"))

    return {
        "ticker": ticker,
        "status": "complete",
        "trace": trace,
        "result": {
            "taxonomy": taxonomy,
            "trend": trend,
            "forecast": forecast,
            "report": report_result,
        },
    }


def run_portfolio_investigation(
    tickers: list[str],
    build_taxonomy,
    compute_trend,
    generate_portfolio_report,
) -> dict:
    """A genuinely different request type from run_investigation — proof the Orchestrator's
    routing is more than a renamed fixed pipeline for one ticker. Routes to Market/Risk Analyst
    agents for EACH ticker (lighter-weight than a full single-ticker investigation — no per-ticker
    Report/Critic/Forecast calls, since a portfolio-level report only needs each ticker's FRI and
    trend direction, not its full narrative), then a single portfolio-level Report Agent call
    synthesizes across all of them. Per-ticker failures are caught individually so one bad ticker
    doesn't abort the whole portfolio view, same principle as run_investigation's per-step
    resilience.
    """
    trace = []
    tickers = [t.strip().upper() for t in tickers if t.strip()]

    trace.append(_trace_step(
        "Orchestrator", "portfolio_investigation_started",
        f"Planning portfolio investigation for {len(tickers)} tickers — routing to per-ticker "
        f"Risk Analyst agents, then a single Portfolio Report Agent (a different route than "
        f"single-ticker investigation, which also calls Forecast/Critic per ticker)",
    ))

    tickers_data = []
    for ticker in tickers:
        try:
            taxonomy = build_taxonomy(ticker)
            trend = compute_trend(ticker)
            fri = taxonomy.get("fri", {}).get("score")
            tickers_data.append({
                "ticker": ticker,
                "fri": fri,
                "confidence": taxonomy.get("fri", {}).get("confidence"),
                "trend_direction": trend.get("direction") if trend else None,
            })
            trace.append(_trace_step(
                "Risk Analyst Agent", "ticker_processed",
                f"{ticker}: FRI {fri if fri is not None else 'unavailable'}"
                + (f", trend {trend['direction']}" if trend else ", no trend data"),
            ))
        except Exception as exc:
            tickers_data.append({"ticker": ticker, "fri": None, "confidence": None, "trend_direction": None})
            trace.append(_trace_step("Risk Analyst Agent", "ticker_failed", f"{ticker}: {exc}"))

    valid_count = sum(1 for t in tickers_data if t["fri"] is not None)
    if valid_count == 0:
        trace.append(_trace_step(
            "Orchestrator", "aborted",
            "No ticker in this portfolio produced a computable FRI — cannot generate a portfolio report",
        ))
        return {"status": "aborted", "trace": trace, "result": {"tickers": tickers_data, "report": None}}

    try:
        report_result = generate_portfolio_report(tickers_data)
        critic = report_result.get("critic") or {}
        verification = report_result.get("evidence_verification") or {}
        trace.append(_trace_step(
            "Portfolio Report Agent", "report_generated",
            f"Report drafted from {valid_count}/{len(tickers)} tickers with real FRI data, "
            f"{len(report_result.get('labeled_claims', []))} labeled claims",
        ))
        trace.append(_trace_step(
            "Portfolio Critic Agent", critic.get("verdict", "unknown"),
            f"{len(critic.get('issues', []))} issue(s) found, "
            f"{critic.get('revisions_requested', 0)} revision(s) requested",
        ))
        trace.append(_trace_step(
            "Evidence Verifier", verification.get("verdict", "unknown"),
            f"{verification.get('unsupported_count', 0)} of {verification.get('total_checked', 0)} "
            f"checked claims had figures not traceable to the source data",
        ))
    except RuntimeError as exc:
        trace.append(_trace_step("Portfolio Report Agent", "failed", str(exc)))
        return {"status": "partial", "trace": trace, "result": {"tickers": tickers_data, "report": None}}

    trace.append(_trace_step("Orchestrator", "investigation_complete", "Portfolio investigation complete"))

    return {
        "status": "complete",
        "trace": trace,
        "result": {"tickers": tickers_data, "report": report_result},
    }
