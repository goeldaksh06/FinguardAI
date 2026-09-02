"""Build a historical, timestamped risk-feature dataset per ticker.

Every score the app has produced so far is "as of right now" — there was no dated history to
learn from, backtest against, or search for similar past situations. This script closes that gap
for the 133 tickers that have both indicator data and collected SEC filings (the two overlap
completely — see the sector's CLAUDE.md session notes): for every trading day in the indicators
CSV, it computes what market_risk and management_governance_risk would have been on that date,
using only data that existed by that date.

No look-ahead: market_risk on day T uses only day T's indicator row (already computed from prices
up to and including T by generate_indicators.py). governance_risk on day T uses only 8-K filings
with filed_at <= T (governance_risk_signal's as_of parameter enforces this) — a filing from next
week cannot influence today's score.

Output: data/processed/risk_history/<TICKER>.csv, columns:
    date, close, market_risk, governance_risk, governance_filings_considered,
    governance_coverage_reliable

IMPORTANT limitation, honestly surfaced rather than hidden: scripts/sec_filings.py only fetched
each ticker's ~10 MOST RECENT filings, not its full history — confirmed by inspection (AAPL's
earliest collected 8-K is 2025-05-12, despite the indicators history going back to 2021). That
means a governance_risk of 0 for a date before the earliest collected 8-K does NOT mean "no risk
existed then" — it means "we have no filing data for that period at all". The
governance_coverage_reliable column is False for any date before the ticker's earliest collected
8-K, so anything built on top of this dataset (a forecasting model, a historical-pattern search)
can filter out the unreliable early rows instead of silently learning from fabricated zeros.

news_event_risk is NOT backfilled here — Google News RSS only returns current headlines, there's
no historical archive available for free, so a historical FRI would need to either exclude that
category (as this script does) or be honest that it's incomplete before that date range.

Run from the project root:
    venv/Scripts/python.exe scripts/build_risk_history.py [--tickers AAPL,MSFT] [--limit 5]
"""
import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))

from filings import list_filings, _score_eight_ks  # noqa: E402
from risk_scoring import stock_risk_score  # noqa: E402

REPO_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
FILINGS_DIR = os.path.join(REPO_ROOT, "data", "raw", "filings")
INDICATORS_DIR = os.path.join(REPO_ROOT, "data", "processed", "market", "indicators")
OUTPUT_DIR = os.path.join(REPO_ROOT, "data", "processed", "risk_history")


def backfill_ticker(ticker: str) -> int:
    indicators_path = os.path.join(INDICATORS_DIR, f"{ticker}.csv")
    if not os.path.exists(indicators_path):
        print(f"  skip {ticker}: no indicators")
        return 0

    df = pd.read_csv(indicators_path, parse_dates=["Date"])
    if df.empty:
        return 0

    filings = list_filings(ticker)
    eight_ks = [f for f in filings if f["form_type"] == "8-K"]

    earliest_filed = None
    for f in eight_ks:
        if f.get("filed_at"):
            dt = __import__("datetime").datetime.fromisoformat(f["filed_at"])
            if earliest_filed is None or dt < earliest_filed:
                earliest_filed = dt

    rows = []
    for _, row in df.iterrows():
        as_of = row["Date"].to_pydatetime()
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=__import__("datetime").timezone.utc)

        market_score, _ = stock_risk_score(row)
        governance = _score_eight_ks(eight_ks, lookback_days=365, reference=as_of)
        coverage_reliable = earliest_filed is not None and as_of >= earliest_filed

        rows.append(
            {
                "date": row["Date"].date().isoformat(),
                "close": round(float(row["Close"]), 2),
                "market_risk": market_score,
                "governance_risk": governance["score"],
                "governance_filings_considered": governance["filings_considered"],
                "governance_coverage_reliable": coverage_reliable,
            }
        )

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, f"{ticker}.csv")
    pd.DataFrame(rows).to_csv(out_path, index=False)
    return len(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", type=str, default=None, help="Comma-separated tickers; default: all with collected filings")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",")]
    else:
        tickers = sorted(os.listdir(FILINGS_DIR))

    if args.limit:
        tickers = tickers[: args.limit]

    print(f"Backfilling risk history for {len(tickers)} tickers...")
    total_rows = 0
    for i, ticker in enumerate(tickers, 1):
        n = backfill_ticker(ticker)
        total_rows += n
        print(f"[{i}/{len(tickers)}] {ticker}: {n} rows")

    print(f"Done. {total_rows} total rows written to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
