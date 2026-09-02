import json
import os
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from filings import list_filings, get_filing_section, governance_risk_signal
from live_market import fetch_live_indicators
from news import news_event_risk_signal, fetch_headlines, build_query
from orchestrator import run_investigation, run_portfolio_investigation
from report_agent import generate_report_with_critique, generate_portfolio_report
from risk_scoring import stock_risk_score as _stock_risk_score, risk_label as _risk_label
from sentiment import score_headlines, sentiment_summary, sentiment_price_divergence

app = FastAPI(title="FinGuard AI API", version="2.0.0")

_MODEL_DIR = Path(__file__).resolve().parent / "model"
_FORECAST_MODEL = None
_FORECAST_METRICS = None
_FORECAST_FEATURES = ["market_risk", "rsi_14", "macd", "macd_signal", "volatility_20", "returns", "ema_spread"]


def _get_forecast_model():
    """Lazily loads the trained forecasting baseline (scripts/train_forecast_model.py) so
    importing this module doesn't force a model load if the endpoint is never hit."""
    global _FORECAST_MODEL, _FORECAST_METRICS
    if _FORECAST_MODEL is None:
        model_path = _MODEL_DIR / "forecast_model.joblib"
        metrics_path = _MODEL_DIR / "forecast_metrics.json"
        if not model_path.exists():
            return None, None
        _FORECAST_MODEL = joblib.load(model_path)
        if metrics_path.exists():
            with open(metrics_path) as f:
                _FORECAST_METRICS = json.load(f)
    return _FORECAST_MODEL, _FORECAST_METRICS

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BACKEND_DIR = os.path.dirname(__file__)
INDICATORS_DIR = os.path.join(BACKEND_DIR, "..", "data", "processed", "market", "indicators")
RISK_HISTORY_DIR = os.path.join(BACKEND_DIR, "..", "data", "processed", "risk_history")


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "FinGuard AI"}


# Data freshness: /api/stock-risk, /api/risk-taxonomy, and /api/watchlist-risk all try
# fetch_live_indicators() (backend/live_market.py) first — a real yfinance call at request time,
# cached ~10 min — so scores stay current rather than reading the static
# data/processed/market/indicators/ CSVs, which were fetched once and found to be 250+ days
# stale for most of the ~9,749-ticker dataset during this session (see CLAUDE.md). The static
# CSVs remain a fallback for when a live fetch fails (network issue, an invalid/delisted ticker,
# or a ticker yfinance doesn't recognize) — when that fallback is used, `freshness.is_stale`
# still reports it honestly rather than silently serving old data as current.
_STALE_THRESHOLD_DAYS = 7


def _data_freshness(date_str: str) -> dict:
    try:
        as_of = pd.to_datetime(date_str, utc=True)
        age_days = (datetime.now(timezone.utc) - as_of.to_pydatetime()).days
    except Exception:
        age_days = None
    return {
        "as_of": date_str,
        "age_days": age_days,
        "is_stale": age_days is not None and age_days > _STALE_THRESHOLD_DAYS,
    }


def _get_indicator_frame(ticker: str) -> tuple[pd.DataFrame, bool]:
    """Live indicator frame if available, else fall back to the static precomputed CSV.
    Returns (dataframe, is_live). Raises HTTPException(404) if neither source has the ticker.
    """
    live_df = fetch_live_indicators(ticker)
    if live_df is not None and not live_df.empty:
        return live_df, True

    path = os.path.join(INDICATORS_DIR, f"{ticker.upper()}.csv")
    if os.path.exists(path):
        df = pd.read_csv(path)
        if not df.empty:
            return df, False

    raise HTTPException(status_code=404, detail=f"No data available for ticker '{ticker}'")


# data/reference/company_master.csv turned out to be entirely empty for company_name/sector/
# industry/exchange (a bug in build_company.py's FMP+yfinance enrichment step — every row of the
# 10,142-ticker file has those fields as NaN, confirmed by inspection). Rather than depend on that
# broken file or run a slow, rate-limit-prone batch re-enrichment job, company info is fetched
# live from yfinance per ticker (same library already used by scripts/market_prices.py) and
# cached in-process, since it rarely changes within a dev session.
_COMPANY_INFO_CACHE: dict[str, dict] = {}


def _get_company_info(ticker: str) -> dict | None:
    ticker = ticker.upper()
    if ticker in _COMPANY_INFO_CACHE:
        return _COMPANY_INFO_CACHE[ticker]

    try:
        import yfinance as yf

        info = yf.Ticker(ticker).info
    except Exception:
        info = None

    result = None
    if isinstance(info, dict) and info.get("longName"):
        result = {
            "name": info.get("longName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "exchange": info.get("exchange"),
        }
    _COMPANY_INFO_CACHE[ticker] = result
    return result


@app.get("/api/stock-tickers")
def stock_tickers(q: str = "", limit: int = 20):
    """List available tickers from the indicators pipeline, optionally filtered by prefix."""
    all_files = os.listdir(INDICATORS_DIR)
    tickers = [f[:-4] for f in all_files if f.endswith(".csv")]
    if q:
        q_upper = q.upper()
        tickers = [t for t in tickers if t.startswith(q_upper)]
    tickers.sort()
    return {"tickers": tickers[:limit], "total_available": len(tickers)}


@app.get("/api/stock-risk/{ticker}")
def stock_risk(ticker: str):
    """Rule-based risk read on a ticker, computed from live-fetched indicators where possible
    (see _get_indicator_frame). Not a trained model — a transparent weighted formula, because
    there's no labeled "this stock was risky" dataset to train against.
    """
    df, is_live = _get_indicator_frame(ticker)
    latest = df.iloc[-1]
    score, reasons = _stock_risk_score(latest)

    history = df.tail(30)[["Date", "Close", "rsi_14", "volatility_20"]].to_dict("records")
    company = _get_company_info(ticker)

    return {
        "ticker": ticker.upper(),
        "company": company,
        "as_of": latest["Date"],
        "freshness": _data_freshness(latest["Date"]),
        "close": round(float(latest["Close"]), 2),
        "risk_score": score,
        "risk_label": _risk_label(score),
        "reasons": reasons,
        "indicators": {
            "rsi_14": round(float(latest["rsi_14"]), 2),
            "macd": round(float(latest["macd"]), 4),
            "macd_signal": round(float(latest["macd_signal"]), 4),
            "volatility_20": round(float(latest["volatility_20"]), 4),
            "ema_20": round(float(latest["ema_20"]), 2),
            "ema_50": round(float(latest["ema_50"]), 2),
        },
        "history": history,
    }


@app.get("/api/filings/{ticker}")
def filings_for_ticker(ticker: str):
    """Real SEC filing metadata already collected by scripts/sec_filings.py for this ticker —
    form type, filed date, description, and a link to the actual SEC document."""
    filings = list_filings(ticker)
    if not filings:
        raise HTTPException(status_code=404, detail=f"No collected filings for ticker '{ticker}'")
    return {"ticker": ticker.upper(), "filings": filings}


@app.get("/api/filings/{ticker}/section")
def filing_section(ticker: str, accession_no: str, document_url: str, section: str = "risk_factors"):
    """Fetch (or return cached) real extracted text for one section of one filing.

    section: "risk_factors" (Item 1A) or "mdna" (Item 7). Not every filing has every section —
    an 8-K has neither, so a 404 here is expected and honest, not a bug.
    """
    try:
        return get_filing_section(ticker, accession_no, document_url, section)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Could not fetch filing document: {exc}")


# The full 17-category taxonomy from the product vision (Liquidity, Credit, Supply Chain, ESG,
# etc.) can't be honestly computed yet — that needs balance-sheet, supplier, and macro data this
# project doesn't collect. Listing them here (instead of silently omitting them) makes the gap
# visible to the API consumer rather than implying the taxonomy is more complete than it is.
_TAXONOMY_NOT_YET_AVAILABLE = [
    "Liquidity", "Credit", "Supply Chain", "Regulatory", "Legal", "Cybersecurity",
    "Geopolitical", "ESG", "Revenue", "Margin", "Debt", "Cash Flow", "Competitive",
    "Concentration",
]

# Fixed, documented weights for the FinGuard Risk Index (FRI) — NOT an LLM-guessed number.
# Rationale: market_risk is continuously available and updates daily, so it anchors the score;
# management_governance_risk is event-based but authoritative when present (an official SEC
# filing); news_event_risk is the noisiest signal (keyword matching on headlines, no source
# verification beyond Google News itself), so it carries the least weight. These weights are a
# starting heuristic, not fit/validated against any outcome — that would require the labeled
# historical dataset this project is only just starting to build (see risk_history/ + CLAUDE.md).
_FRI_WEIGHTS = {
    "market_risk": 0.45,
    "management_governance_risk": 0.35,
    "news_event_risk": 0.20,
}


def _compute_fri(categories: dict) -> dict:
    """Combine available category scores into one overall FRI using fixed weights, renormalized
    over whatever categories actually have data. Confidence reflects how much of the taxonomy's
    weight was actually backed by real data for this ticker, not a fabricated certainty.
    """
    available = {
        name: cat["score"]
        for name, cat in categories.items()
        if cat["score"] is not None and name in _FRI_WEIGHTS
    }
    if not available:
        return {"score": None, "confidence": 0.0, "weights_used": {}}

    weight_sum = sum(_FRI_WEIGHTS[name] for name in available)
    normalized_weights = {name: _FRI_WEIGHTS[name] / weight_sum for name in available}
    fri = sum(available[name] * normalized_weights[name] for name in available)
    confidence = round(weight_sum, 2)

    return {
        "score": round(fri, 1),
        "confidence": confidence,
        "weights_used": {name: round(w, 2) for name, w in normalized_weights.items()},
    }


def _build_taxonomy(ticker: str) -> dict:
    """Core taxonomy + FRI computation, shared by the single-ticker endpoint and the watchlist
    batch endpoint so there's one implementation, not two copies."""
    df, is_live = _get_indicator_frame(ticker)
    latest = df.iloc[-1]
    market_score, market_reasons = _stock_risk_score(latest)

    governance = governance_risk_signal(ticker)
    company = _get_company_info(ticker)
    news_signal = news_event_risk_signal(company["name"] if company else None, ticker)

    categories = {
        "market_risk": {
            "score": market_score,
            "basis": "RSI, MACD, 20-day volatility, price vs. 50-day EMA",
            "reasons": market_reasons,
        },
        "management_governance_risk": {
            "score": governance["score"],
            "basis": "SEC Form 8-K item codes filed in the last 365 days",
            "reasons": governance["reasons"],
            "filings_considered": governance["filings_considered"],
        },
        "news_event_risk": {
            "score": news_signal["score"],
            "basis": "Keyword-matched risk events in real headlines (Google News RSS, last 14 days)",
            "reasons": news_signal["reasons"],
            "articles_considered": news_signal["articles_considered"],
        },
    }

    fri = _compute_fri(categories)

    return {
        "ticker": ticker.upper(),
        "company": company,
        "fri": fri,
        "freshness": _data_freshness(latest["Date"]),
        "categories": categories,
        "not_yet_available": _TAXONOMY_NOT_YET_AVAILABLE,
        "note": (
            "Only categories with a real, traceable data source behind them are scored. "
            "management_governance_risk is null when no 8-K filings have been collected for "
            "this ticker (133 of ~9,749 tickers currently have collected filings), and "
            "news_event_risk is null only if the news fetch itself failed — both distinguish "
            "'no data' from 'no risk found'. fri combines available categories using fixed, "
            "documented weights (see _FRI_WEIGHTS in backend/app.py) renormalized over whatever "
            "categories have real data — confidence reflects how much of the total weight was "
            "actually backed by data for this ticker, not a trained/validated probability."
        ),
    }


@app.get("/api/risk-taxonomy/{ticker}")
def risk_taxonomy(ticker: str):
    """Real, structured risk categories for a ticker, plus the combined FRI."""
    return _build_taxonomy(ticker)


@app.get("/api/news-sentiment/{ticker}")
def news_sentiment(ticker: str):
    """FinBERT sentiment analysis over real recent headlines — additive to, not a replacement
    for, news_event_risk's keyword matching (see backend/sentiment.py for why they're kept
    separate). Deliberately its own endpoint rather than folded into /api/risk-taxonomy or
    /api/watchlist-risk: FinBERT inference is comparatively expensive (CPU-bound, ~50 headlines
    per call), and the watchlist batch endpoint needs to stay fast for several tickers at once.
    This is meant for someone deliberately drilling into one ticker, not the default view.

    Explicitly NOT a market prediction — see the module docstring in sentiment.py. Returns every
    per-headline score, not just the aggregate, so this data is usable for whatever further
    analysis someone wants to do with it, not just FinGuard's own summary.
    """
    company = _get_company_info(ticker)
    query = build_query(company["name"] if company else None, ticker)
    try:
        headlines = fetch_headlines(query)
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Could not fetch headlines: {exc}")

    if not headlines:
        return {
            "ticker": ticker.upper(),
            "net_sentiment": None,
            "trend": None,
            "counts": {},
            "divergence": None,
            "headlines": [],
            "note": "No headlines found for this ticker.",
        }

    scored = score_headlines(headlines)
    summary = sentiment_summary(scored)

    price_change_pct = None
    df = fetch_live_indicators(ticker)
    if df is not None and len(df) >= 6:
        recent_close = float(df.iloc[-1]["Close"])
        past_close = float(df.iloc[-6]["Close"])
        if past_close:
            price_change_pct = (recent_close - past_close) / past_close * 100

    divergence = sentiment_price_divergence(summary["net_sentiment"], price_change_pct)

    return {
        "ticker": ticker.upper(),
        "net_sentiment": summary["net_sentiment"],
        "trend": summary["trend"],
        "counts": summary["counts"],
        "price_change_pct_5d": round(price_change_pct, 2) if price_change_pct is not None else None,
        "divergence": divergence,
        "headlines": summary["headlines"],
        "note": (
            "net_sentiment: FinBERT-scored average across recent headlines, -100 (uniformly "
            "negative) to +100 (uniformly positive), weighted by each headline's confidence. "
            "trend compares earlier vs. later headlines in the window ('worsening'/'improving'/"
            "'stable'). This is a real signal from a finance-tuned model (ProsusAI/finbert), NOT "
            "a market prediction — news sentiment is a weak, noisy signal at best. Every "
            "headline's individual score is included so this can be used for further analysis "
            "beyond FinGuard's own aggregate."
        ),
    }


def _compute_trend(ticker: str, lookback_trading_days: int = 30) -> dict | None:
    """Real trend: compares current market_risk to its value N trading days ago. Both values now
    come from the SAME live-fetched frame (fetch_live_indicators, ~6 months of history — plenty
    to cover a 30-trading-day lookback), not the static scripts/build_risk_history.py backfill —
    that backfill stopped being refreshed and its "current" row was found to be 250+ days stale
    during this session, which would have silently broken this comparison (comparing a live
    "now" against a stale "now" mislabeled as recent history). The backfilled dataset still
    exists as a separate, explicitly historical artifact (data/processed/risk_history/) for
    future ML training, but this live endpoint no longer depends on it.

    This is a statistical comparison against actual past values — NOT a trained forecasting
    model. A real predictive model (e.g. "probability risk increases over the next 30 days") is
    future work; this is the honest, buildable slice of that idea.
    """
    df = fetch_live_indicators(ticker)
    if df is None or len(df) < lookback_trading_days + 1:
        return None

    current = df.iloc[-1]
    past = df.iloc[-1 - lookback_trading_days]

    current_score, _ = _stock_risk_score(current)
    past_score, _ = _stock_risk_score(past)
    change = round(current_score - past_score, 2)

    if change > 5:
        direction = "increasing"
    elif change < -5:
        direction = "decreasing"
    else:
        direction = "stable"

    result = {
        "lookback_trading_days": lookback_trading_days,
        "market_risk_change": change,
        "direction": direction,
        "from_date": str(past["Date"]),
        "from_value": past_score,
        "to_date": str(current["Date"]),
        "to_value": current_score,
        "method": (
            f"Compares market_risk on {current['Date']} to its value {lookback_trading_days} "
            "trading days earlier, both freshly computed from live-fetched price history — a "
            "backward-looking comparison, not a prediction of future risk."
        ),
    }

    # Governance risk at each end of the window, computed directly from real filing dates
    # (governance_risk_signal's as_of parameter) — not dependent on any stale precomputed data.
    gov_now = governance_risk_signal(ticker, as_of=pd.Timestamp(current["Date"]).to_pydatetime())
    gov_past = governance_risk_signal(ticker, as_of=pd.Timestamp(past["Date"]).to_pydatetime())
    if gov_now["score"] is not None and gov_past["score"] is not None:
        result["governance_risk_change"] = round(gov_now["score"] - gov_past["score"], 2)

    return result


@app.get("/api/risk-trend/{ticker}")
def risk_trend(ticker: str, lookback_days: int = 30):
    trend = _compute_trend(ticker, lookback_days)
    if trend is None:
        raise HTTPException(
            status_code=404,
            detail=f"Could not fetch enough live price history for '{ticker}' to compute a "
            f"{lookback_days}-trading-day trend (invalid ticker, or too newly listed).",
        )
    return trend


def _compute_forecast(ticker: str) -> dict | None:
    """Shared core for /api/risk-forecast and the Report Agent — one implementation, not two
    copies that could drift, same pattern as _build_taxonomy/_compute_trend."""
    model, metrics = _get_forecast_model()
    if model is None:
        return None

    df = fetch_live_indicators(ticker)
    if df is None or df.empty:
        return None

    latest = df.iloc[-1]
    market_risk, _ = _stock_risk_score(latest)
    ema_spread = (latest["ema_20"] - latest["ema_50"]) / latest["ema_50"]

    features = pd.DataFrame([{
        "market_risk": market_risk,
        "rsi_14": latest["rsi_14"],
        "macd": latest["macd"],
        "macd_signal": latest["macd_signal"],
        "volatility_20": latest["volatility_20"],
        "returns": latest["returns"],
        "ema_spread": ema_spread,
    }])[_FORECAST_FEATURES]

    probability = float(model.predict_proba(features)[0, 1])
    importances = dict(zip(_FORECAST_FEATURES, [round(float(x), 4) for x in model.feature_importances_]))

    return {
        "ticker": ticker.upper(),
        "current_market_risk": round(float(market_risk), 2),
        "as_of": str(pd.Timestamp(latest["Date"]).date()),
        "horizon_trading_days": 30,
        "probability_market_risk_increase_10pt": round(probability, 4),
        "feature_importances": importances,
        "model_test_metrics": metrics["xgboost"]["test"] if metrics else None,
        "naive_baseline_test_metrics": metrics["naive_baseline"]["test"] if metrics else None,
        "method": (
            "Real trained XGBoost classifier (walk-forward validated, not an LLM guess), "
            "predicting P(market_risk rises >=10 points within 30 trading days) from current "
            "technical indicators. This is a genuine forward-looking prediction, unlike "
            "/api/risk-trend which only compares past values. Test-set performance is modest "
            "(see model_test_metrics) — treat this as an early signal, not a certainty."
        ),
    }


@app.get("/api/risk-forecast/{ticker}")
def risk_forecast(ticker: str):
    """First real Forecasting Agent baseline (scripts/train_forecast_model.py) — a trained
    XGBoost classifier, NOT an LLM guess, predicting the probability that market_risk rises by
    >=10 points over the next 30 trading days. Walk-forward validated (chronological train/val/
    test split with a purge gap), measured against a naive majority-class baseline: test-set
    ROC-AUC 0.75 vs. the naive baseline's 0.50, PR-AUC 0.51 vs. 0.29 base rate — a real, if
    modest, improvement, not a fabricated confidence number. See backend/model/forecast_metrics.json
    for the full evaluation. This is deliberately narrow in scope (see the module docstring in
    scripts/train_forecast_model.py): trained on market_risk + technical indicators only, no
    governance/news features, because those have coverage gaps that would silently degrade the
    model for tickers/dates without them. Distinct from /api/risk-trend, which is a real but
    purely backward-looking comparison — this is the first genuinely forward-looking prediction
    in the product.
    """
    forecast = _compute_forecast(ticker)
    if forecast is None:
        model, _ = _get_forecast_model()
        if model is None:
            raise HTTPException(status_code=503, detail="Forecast model not trained yet — run scripts/train_forecast_model.py")
        raise HTTPException(status_code=404, detail=f"Could not fetch live data for '{ticker}'.")
    return forecast


@app.get("/api/report/{ticker}")
def report(ticker: str):
    """Report Agent + Critic Agent — the first real agentic feedback loop in FinGuard AI. Takes
    the already-computed FRI/taxonomy, trend, and forecast (all real, deterministic) and asks an
    LLM (Groq, openai/gpt-oss-120b — free tier, no cost) to explain them in plain language, with
    every claim labeled FACT / MODEL PREDICTION / AI INTERPRETATION per the evidence-first
    principle in ROADMAP.md §21. A deterministic Critic Agent (backend/critic_agent.py) then
    checks evidence sufficiency and can send the report back for one revision with specific
    concerns attached — see report_agent.py's generate_report_with_critique().
    """
    taxonomy = _build_taxonomy(ticker)
    trend = _compute_trend(ticker)
    forecast = _compute_forecast(ticker)

    try:
        return generate_report_with_critique(ticker, taxonomy, trend, forecast)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@app.get("/api/investigate/{ticker}")
def investigate(ticker: str):
    """Orchestrator/Planner entry point (backend/orchestrator.py, ROADMAP.md §5) — the "Investigate
    X's emerging financial risks" demo endpoint. Unlike /api/report, which always calls the full
    fixed pipeline, this checks what data is actually available for the ticker FIRST and adapts:
    aborts early with a clear reason if there's no market data at all, and lets individual steps
    (trend, forecast) come back empty without failing the whole investigation, since the Report
    Agent already handles missing categories honestly. Returns a step-by-step execution trace
    (agent, decision, detail, timestamp) alongside the final result — a real, if small, instance
    of ROADMAP.md §32's "live execution trace" concept, not a fabricated log.
    """
    return run_investigation(
        ticker,
        get_indicator_frame=_get_indicator_frame,
        build_taxonomy=_build_taxonomy,
        compute_trend=_compute_trend,
        compute_forecast=_compute_forecast,
        generate_report_with_critique=generate_report_with_critique,
    )


@app.get("/api/investigate-portfolio")
def investigate_portfolio(tickers: str):
    """Second real request type for the Orchestrator (backend/orchestrator.py) to route to —
    proof its planning logic is more than a renamed fixed pipeline for one ticker (ROADMAP.md
    §5/§33). `tickers` is a comma-separated list, same format as /api/watchlist-risk. Routes to
    a lighter-weight per-ticker path (FRI + trend only, no per-ticker Forecast/Report/Critic
    calls) followed by ONE portfolio-level Report Agent call synthesizing across all tickers.
    """
    return run_portfolio_investigation(
        tickers.split(","),
        build_taxonomy=_build_taxonomy,
        compute_trend=_compute_trend,
        generate_portfolio_report=generate_portfolio_report,
    )


@app.get("/api/watchlist-risk")
def watchlist_risk(tickers: str):
    """Batch endpoint for the watchlist view: one request instead of N. `tickers` is a
    comma-separated list. Each entry gets its taxonomy/FRI and, where historical data exists
    (the 133 filing-covered tickers), its real trend — invalid/unavailable tickers are reported
    per-item rather than failing the whole batch.
    """
    results = []
    for raw in tickers.split(","):
        ticker = raw.strip().upper()
        if not ticker:
            continue
        try:
            taxonomy = _build_taxonomy(ticker)
        except HTTPException as exc:
            results.append({"ticker": ticker, "error": exc.detail})
            continue
        taxonomy["trend"] = _compute_trend(ticker)
        results.append(taxonomy)
    return {"results": results}


@app.get("/")
def root():
    return {"message": "FinGuard AI API is running"}
