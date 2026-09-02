# FinGuard AI

**An agentic financial risk intelligence platform** — a multi-agent backend that investigates a
stock's risk profile using real market data, SEC filings, news, and machine learning, then has a
language model explain the findings with every claim labeled as fact, model prediction, or
interpretation.

FinGuard is built around a **watchlist**, not a one-shot lookup: add tickers you actually hold,
and it surfaces a real, evidence-linked risk score plus what's changed since you last checked.

## What it does

- **Risk scoring (FinGuard Risk Index).** Combines three real, independently-computed signals —
  technical market indicators, SEC Form 8-K governance events, and keyword-matched news risk —
  into one transparent, weighted score. No black-box number: every category is traceable to its
  source evidence, and missing data is reported as missing, never silently treated as zero risk.
- **Forecasting.** A walk-forward-validated XGBoost classifier predicts the probability that a
  stock's risk rises materially over the next 30 trading days, trained on historical market data
  with a strict no-look-ahead split. Measured against a naive baseline, not just reported alone.
- **News sentiment.** FinBERT (a finance-tuned transformer) scores real headlines for sentiment,
  trend, and divergence from price action — a separate, additive signal alongside the keyword-based
  event detector.
- **Multi-agent investigation.** An orchestrator plans and routes a request across specialized
  agents — Market, Risk Analyst, History, Forecast — then a Report Agent (LLM) writes a plain-
  language summary. A Critic Agent checks the report's evidence sufficiency and can send it back
  for revision; an Evidence Verifier independently checks that every factual claim traces back to
  a real number in the source data. The full execution trace is exposed to the frontend.
- **Portfolio-level investigation.** A second orchestration path aggregates risk across an entire
  watchlist and produces one synthesized report, with its own portfolio-scoped critic check.
- **Real filings, on demand.** Fetches and extracts actual Risk Factors / MD&A sections from SEC
  EDGAR filings, not summaries — the original text, cached after first fetch.
- **Change alerts.** The watchlist remembers each ticker's risk score from your last visit and
  flags meaningful moves, so it's a tool you return to rather than a static lookup.

## Architecture

```
                         User
                           |
                           v
                    Orchestrator
                           |
              +------------+------------+
              |                         |
       Single-ticker route      Portfolio route
              |                         |
    Market -> Risk Analyst        Risk Analyst (per ticker)
       |          |                     |
    History   Forecast          Portfolio Report Agent (LLM)
       |          |                     |
       +----------+                Critic Agent
              |                         |
       Report Agent (LLM)        Evidence Verifier
              |
        Critic Agent
              |
      Evidence Verifier
              |
       Final response + trace
```

Every agent has a distinct job:

| Agent | Responsibility |
|---|---|
| **Orchestrator** | Checks data availability, decides which agents to invoke, aborts early on missing data |
| **Market Agent** | Live technical indicators (RSI, MACD, volatility, EMA) via yfinance |
| **Risk Analyst Agent** | Combines market, governance, and news signals into the FinGuard Risk Index |
| **History Agent** | Backward-looking trend comparison against real historical values |
| **Forecast Agent** | Trained XGBoost model, walk-forward validated, forward-looking risk probability |
| **Report Agent** | LLM call that explains the computed data — never invents a number |
| **Critic Agent** | Deterministic evidence-sufficiency check; can request one revision |
| **Evidence Verifier** | Checks every factual claim in the report against the real source data |

The language model is the *communication layer*, not the source of truth: every number it
discusses was computed deterministically beforehand, and every claim it makes is labeled `FACT`,
`MODEL PREDICTION`, or `AI INTERPRETATION` in the response.

## Tech stack

- **Backend:** FastAPI, pandas, scikit-learn, XGBoost, Transformers (FinBERT), Groq API
- **Frontend:** React 18 + Vite, plain JS
- **Data sources:** yfinance (live market data), SEC EDGAR (filings), Google News RSS
- **Storage:** flat CSV/JSON for market/reference data, browser `localStorage` for the watchlist

## Getting started

### Backend

```bash
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

pip install torch==2.13.0 --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt

cp config/api_keys.example.yaml config/api_keys.yaml
# fill in your own API keys (see below)

cd backend
uvicorn app:app --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The app runs at `http://localhost:5173` by default and expects the backend at
`http://localhost:8000`.

### API keys required

| Key | Used for | Required to run? |
|---|---|---|
| `groq_api_key` | LLM calls via [Groq](https://console.groq.com), free tier | Yes, for the Report/Critic/Orchestrator endpoints |
| `sec_api_key` | Collecting more SEC filings via [sec-api.io](https://sec-api.io) | No — a sample is already committed (see below) |

Market data (yfinance) and news (Google News RSS) need no key at all.

## Project structure

```
backend/
  app.py                 FastAPI app, all endpoints
  orchestrator.py         Agent routing and execution trace
  report_agent.py          Report Agent (LLM) + prompt logic
  critic_agent.py           Evidence-sufficiency checks
  evidence_verifier.py       Claim-vs-source verification
  live_market.py               Live technical indicator computation
  filings.py                     SEC EDGAR fetch/extraction
  news.py                          Keyword-based news event risk
  sentiment.py                       FinBERT sentiment scoring
  risk_scoring.py                      Shared risk-scoring formula
  model/                                  Trained forecast model artifact
frontend/
  src/App.jsx             All React components
scripts/
  train_forecast_model.py    Walk-forward model training
  generate_indicators.py       Technical indicator pipeline
  sec_filings.py                 SEC filing collection
  build_risk_history.py            Historical dataset backfill
```

## Running with no setup beyond installing dependencies

Market data, news, and sentiment are fetched live at request time (yfinance + Google News RSS +
FinBERT) — no API key or pre-collected data needed for those. A small real sample of collected
SEC filings is committed for **AAPL, MSFT, NVDA, GOOGL, JPM, and JNJ** so governance risk and the
full FRI are populated out of the box for those tickers; any other ticker will correctly show
governance risk as unavailable (not a fake zero) until you run `scripts/sec_filings.py` or
`scripts/add_filings.py` to collect more. The forecast model (`backend/model/forecast_model.joblib`)
is a pre-trained artifact and works for any ticker immediately.

## Deployment

**Frontend (Vercel):** deploy `frontend/` as a static Vite build. Set an environment variable
`VITE_API_BASE` pointing at your deployed backend's URL (e.g. `https://finguard-api.onrender.com`)
— without it, the frontend defaults to `http://localhost:8000` for local development.

**Backend (Render, or any host that runs a long-lived Python process):**
- Root directory: `backend/`
- Build command: `pip install -r ../requirements-deploy.txt`
- Start command: `uvicorn app:app --host 0.0.0.0 --port $PORT`
- Environment variable: `groq_api_key` isn't read from the environment directly — set it in
  `config/api_keys.yaml` on the host, or export `GROQ_API_KEY` (both are checked).

`requirements-deploy.txt` is a lean build that excludes `torch`/`transformers` (FinBERT), so it
fits comfortably on a free-tier instance (~512MB RAM). Every endpoint works except
`/api/news-sentiment`, which returns a clear 503 explaining why rather than crashing the server.
For full functionality including sentiment scoring, use `requirements.txt` on a host with more
memory (roughly 1-2GB+).

Vercel is not suitable for the backend itself — its serverless functions cap deployment size well
below what `torch`/`transformers`/`xgboost`/`pandas` need together.

## Notes on scope

FinGuard prioritizes real data and honest signal quality over feature breadth:

- Risk scores are transparent, documented formulas — not fitted against labeled outcomes yet.
- SEC filing coverage is currently a curated set of large-cap tickers, not the full market.
- The forecasting model is a genuine first baseline (measured, modest improvement over a naive
  baseline) — not a claim of high-accuracy prediction.
- No knowledge graph or RAG layer yet; evidence retrieval is direct, not vector search.

## License

MIT
