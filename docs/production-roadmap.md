# From demo to trustworthy: what production-grade would actually require

FinGuard AI, as it stands, is a real, honestly-built demonstration of good AI engineering
practice — transparent scoring, no fabricated numbers, an LLM whose output is checked rather than
trusted blindly. It is **not** validated well enough to inform a real financial decision. This
document is the honest gap between those two states, not a claim that the gap is closed.

## 1. Outcome-validated scoring (the core trust problem)

The FinGuard Risk Index currently combines three signals with fixed, hand-picked weights
(market 45% / governance 35% / news 20%). Nobody has checked whether a high FRI actually predicts
real drawdowns. That's the single biggest gap between "looks rigorous" and "is rigorous."

**What closing it looks like:**
- For every historical `(ticker, date)` pair already in `data/processed/risk_history/`, compute a
  real outcome label: did the stock draw down >15% in the following 30/60/90 days? Underperform
  its sector?
- Fit the FRI's category weights against that real outcome (logistic regression or similar,
  interpretable — not a black box) instead of hand-picking them, using the same no-look-ahead
  walk-forward discipline `scripts/train_forecast_model.py` already established for the forecast
  model.
- Report **calibration**, not just accuracy: when FinGuard says "70% risk," does that actually
  happen ~70% of the time historically? This is currently unmeasured and is the number an analyst
  actually needs.

## 2. Redundant, SLA-backed data feeds

Free tiers are the honest reason this has been unreliable in testing — a Yahoo Finance timeout, a
sec-api.io free-tier quota wall hit mid-session, a Render cold start. None of that is acceptable
in a tool someone might act on.

| Signal | Current (free) | Production alternative |
|---|---|---|
| Market data | yfinance (unofficial, rate-limited) | Polygon.io or Alpha Vantage premium — official API, real SLA |
| SEC filings | sec-api.io free (100 req quota) | sec-api.io paid tier, or SEC's own EDGAR full-text search API |
| News | Google News RSS | NewsAPI paid or Benzinga News API — licensed, structured |
| Redundancy | single source per signal | 2 providers per signal with automatic failover, so one outage doesn't blank a score |

## 3. Infrastructure that doesn't cold-start or 404

- Move off free-tier hosting to an always-on instance (Fly.io, AWS Fargate, or Render's paid
  tier) — no cold starts, predictable latency.
- Add Redis for caching — live data is currently re-fetched repeatedly; a real cache layer cuts
  both cost and flakiness.
- Connect the Postgres instance already declared in `config/db_config.yaml` (never actually
  wired up) for a real audit trail: every report, every score, timestamped and stored — not just
  returned and forgotten.

## 4. Human-in-the-loop, never full automation

- An analyst-facing "flag this report" / "confirm this assessment" workflow, with that feedback
  stored and eventually used to retrain the FRI weights — this is what earns trust over time, not
  a bigger model.
- The Report Agent's output should never be the last step before a decision. It's a first-pass
  triage tool that surfaces evidence for a human to verify — which is already the intent behind
  the FACT / MODEL PREDICTION / AI INTERPRETATION labeling, just not yet enforced by workflow.

## 5. Compliance, before any of the above matters

- Explicit "not investment advice, a research tool" positioning everywhere the product is shown —
  in the app (done, see `DisclaimerBanner` in `frontend/src/App.jsx`) and anywhere it's linked
  from externally.
- Rate limiting and a real ToS review on every data source before scaling usage.
- If this ever handles real user data or decisions at any scale: this becomes a regulated space
  (investment adviser regulation varies by jurisdiction). That needs a real conversation with
  someone qualified before any real user relies on it — not something a disclaimer alone resolves.

## What's already true, for balance

Not everything above is starting from zero:
- The forecast model already does real walk-forward validation with a purge gap — the *pattern*
  for outcome-validated scoring exists, it just hasn't been applied to the FRI weights yet.
- The Critic Agent and Evidence Verifier are real, working hallucination guards, not aspirational.
- `null` vs. `0` discipline is enforced everywhere — missing data has never been silently treated
  as "no risk."

The gap isn't "nothing works." It's "nothing here has been validated against real outcomes at the
rigor a real financial decision deserves" — and that's the honest line this document exists to
keep visible.
