"""Broadens SEC filing collection past the original 133-ticker priority list in
scripts/sec_filings.py, per docs/roadmap.md's "next steps" (broaden filing coverage so more
tickers have real management_governance_risk/FRI/trend data, not just market_risk-only).

Deliberately a separate script rather than editing sec_filings.py's hardcoded priority_100 list
in place — same reasoning as scripts/add_tickers.py: reuses the existing fetch/save/log logic
(fetch_filings_with_fallback, save_filing, append_log) for an explicit ticker list, without
depending on the broken data/reference/company_master.csv (see CLAUDE.md for that bug) or
re-fetching the 133 tickers already collected. Tickers are the exact strings used by
data/processed/market/indicators/<TICKER>.csv (yfinance-style, e.g. "BRK-B" not "BRK.B"), so
whatever gets collected here is immediately usable by the live backend with zero code changes —
same "new data drops into existing endpoints" pattern as add_tickers.py.
"""
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.sec_filings import save_filing, append_log, API_KEY, ENDPOINT_CANDIDATES

# A leaner single-request fetch (primary endpoint + primary header only, short timeout) instead of
# sec_filings.py's full fetch_filings_with_fallback — that function tries 4 endpoints x 3 header
# variants x up to 2 requests each with a 30s timeout, which is fine for a handful of tickers but
# means a genuinely-failing ticker can stall for over 10 minutes. The primary endpoint/header combo
# is what every one of the original 133 tickers actually succeeded on, so this trades a small
# chance of recovering a ticker via a fallback path for making failures fail fast.
_PRIMARY_URL = "https://api.sec-api.io/filings/query"
_PRIMARY_HEADERS = {"Authorization": API_KEY, "Content-Type": "application/json"}
_FETCH_TIMEOUT = 8


def fast_fetch(ticker: str, size: int = 10) -> list[dict]:
    body = {
        "query": {"query_string": {"query": f"ticker:{ticker} AND formType:(10-K OR 10-Q OR 8-K)"}},
        "from": 0,
        "size": size,
        "sort": [{"filedAt": {"order": "desc"}}],
    }
    resp = requests.post(_PRIMARY_URL, json=body, headers=_PRIMARY_HEADERS, timeout=_FETCH_TIMEOUT)
    if resp.status_code != 200:
        return []
    data = resp.json()
    if isinstance(data, dict) and "filings" in data:
        return data.get("filings", [])
    if isinstance(data, list):
        return data
    return []


def bounded_fetch(ticker: str, size: int = 10) -> list[dict]:
    """A second pass for tickers fast_fetch() couldn't find — tries the first 2 endpoint
    candidates x 2 header variants (4 combos) with a short timeout each, instead of
    fetch_filings_with_fallback's full 4x3x2 matrix at 30s per request (which is what caused the
    multi-minute stalls on failing tickers). Caps worst case at ~4*10s=40s per ticker instead of
    potentially 12+ minutes, while still getting most of the real recovery value the fallback
    endpoints provided for the original 133 tickers.
    """
    body = {
        "query": {"query_string": {"query": f"ticker:{ticker} AND formType:(10-K OR 10-Q OR 8-K)"}},
        "from": 0,
        "size": size,
        "sort": [{"filedAt": {"order": "desc"}}],
    }
    headers_list = [
        {"Authorization": API_KEY, "Content-Type": "application/json"},
        {"x-api-key": API_KEY, "Content-Type": "application/json"},
    ]
    for base in ENDPOINT_CANDIDATES[:2]:
        for headers in headers_list:
            try:
                resp = requests.post(base, json=body, headers=headers, timeout=_FETCH_TIMEOUT)
            except requests.exceptions.RequestException:
                continue
            if resp.status_code != 200:
                continue
            try:
                data = resp.json()
            except ValueError:
                continue
            if isinstance(data, dict) and "filings" in data:
                return data.get("filings", [])
            if isinstance(data, list):
                return data
    return []

ALREADY_COLLECTED = set(os.listdir(os.path.join("data", "raw", "filings"))) if os.path.exists(
    os.path.join("data", "raw", "filings")
) else set()

# Next tranche of real, well-known US-listed tickers not already in the original 133-ticker
# priority list — large-cap names spanning tech, finance, healthcare, industrials, consumer,
# energy, and utilities, chosen for broad sector coverage rather than just more mega-cap tech.
NEXT_TRANCHE = [
    # Tech / software / semis
    "MDB", "TEAM", "WDAY", "OKTA", "VEEV", "HUBS", "CDNS", "SNPS", "KLAC", "MRVL",
    "ON", "SWKS", "MCHP", "ADI", "NXPI", "WDC", "STX", "HPQ", "DELL", "NTAP",
    "FTNT", "CYBR", "S", "PATH", "U", "COIN", "RBLX", "DASH", "SNAP", "PINS",
    "TTD", "AKAM", "VRSN", "JNPR", "FFIV", "CDW", "PAYX", "FIS", "GPN", "MSCI",
    # Financials
    "COF", "USB", "PNC", "TFC", "BK", "STT", "MET", "PRU", "AIG", "ALL",
    "TRV", "PGR", "CB", "MMC", "AON", "ICE", "CME", "NDAQ", "MCO", "CBOE",
    # Healthcare
    "DHR", "BMY", "GILD", "VRTX", "REGN", "BIIB", "ILMN", "IDXX", "ZTS", "DXCM",
    "ALGN", "HOLX", "RMD", "EW", "BSX", "MDT", "BAX", "BDX", "CI", "HUM",
    "CNC", "MOH", "ELV",
    # Consumer
    "MDLZ", "KHC", "GIS", "K", "HSY", "STZ", "MNST", "KDP", "CL", "KMB",
    "CLX", "CHD", "EL", "W", "CVNA", "EXPE", "MELI",
    # Industrials / transport / energy
    "MMM", "HON", "EMR", "ETN", "ITW", "PH", "ROK", "DOV", "CSX", "UNP",
    "NSC", "LUV", "DAL", "UAL", "F", "GM", "OXY", "SLB", "HAL", "BKR",
    "PSX", "VLO", "MPC", "KMI", "WMB", "OKE", "EOG", "DVN", "COP",
    # Real estate / utilities
    "PLD", "AMT", "CCI", "EQIX", "PSA", "O", "SPG", "WELL", "DLR", "EXR",
    "AEP", "EXC", "XEL", "ED", "PEG", "WEC", "ES", "FE", "ETR", "EIX",
]


def main():
    indicators_dir = os.path.join("data", "processed", "market", "indicators")
    tickers = [
        t for t in NEXT_TRANCHE
        if t not in ALREADY_COLLECTED and os.path.exists(os.path.join(indicators_dir, f"{t}.csv"))
    ]
    skipped_no_indicators = [t for t in NEXT_TRANCHE if t not in ALREADY_COLLECTED and t not in tickers]
    print(f"{len(ALREADY_COLLECTED)} tickers already have collected filings.")
    print(f"{len(tickers)} new tickers to fetch (have indicator data, not yet collected).")
    if skipped_no_indicators:
        print(f"Skipped (no indicator data, likely a bad/delisted ticker): {skipped_no_indicators}")

    logs = []
    for i, ticker in enumerate(tickers, start=1):
        print(f"[{i}/{len(tickers)}] Fetching: {ticker}", flush=True)
        try:
            filings = fast_fetch(ticker, size=10)
            if not filings:
                filings = bounded_fetch(ticker, size=10)
            if not filings:
                print(f"  -> No filings found for {ticker}", flush=True)
            else:
                print(f"  -> {len(filings)} filing(s) found", flush=True)
            for f in filings:
                meta = save_filing(ticker, f)
                logs.append(meta)
        except Exception as e:
            print(f"ERROR for {ticker}: {e}", flush=True)
        time.sleep(0.35)

    if logs:
        append_log(logs)
        print(f"Saved {len(logs)} filing records; log updated.")
    else:
        print("No filings saved; no log updated.")

    total_now = len(os.listdir(os.path.join("data", "raw", "filings")))
    print(f"Done. Total tickers with collected filings: {total_now}")


if __name__ == "__main__":
    main()
