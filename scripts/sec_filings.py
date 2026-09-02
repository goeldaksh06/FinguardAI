# scripts/sec_filings.py
import os
import sys
import time
import json
import requests
import pandas as pd
from typing import List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.config_loader import get_api_keys

# -----------------------------
# CONFIG
# -----------------------------
API_KEY = get_api_keys()["sec_api_key"]

# Primary candidate endpoints (tries in order). We'll attempt each until one works.
ENDPOINT_CANDIDATES = [
    "https://api.sec-api.io/filings/query",   # recommended for Query API
    "https://api.sec-api.io/filings/search",  # sometimes used
    "https://api.sec-api.io/filings",         # enterprise (may 404)
    "https://api.sec-api.io",                 # base endpoint (docs examples sometimes use this)
]

# Rate limit pause between requests (seconds)
PAUSE = 0.35

# -----------------------------
# UTIL: Detect ticker column
# -----------------------------
def detect_ticker_column(df: pd.DataFrame) -> str:
    candidates = [c for c in df.columns if c.lower().startswith("ticker")]
    for c in df.columns:
        if c.lower() == "ticker":
            return c
    for c in candidates:
        if df[c].dropna().astype(str).str.len().mean() > 1:
            return c
    for c in df.columns:
        sample = df[c].dropna().astype(str).head(50).tolist()
        if sample and all(0 < len(s) <= 6 and s.upper() == s for s in sample[:10]):
            return c
    raise ValueError("No usable ticker column found in CSV!")

# -----------------------------
# API: Try multiple endpoints + auth styles
# -----------------------------
def _try_post(url: str, json_body: dict, headers: dict, params: dict = None, timeout: int = 30):
    try:
        resp = requests.post(url, json=json_body, headers=headers, params=params, timeout=timeout)
        return resp
    except Exception as e:
        return e

def fetch_filings_with_fallback(ticker: str, size: int = 10) -> List[dict]:
    query_body_queryapi = {
        "query": {
            "query_string": {
                "query": f"ticker:{ticker} AND formType:(10-K OR 10-Q OR 8-K)"
            }
        },
        "from": 0,
        "size": size,
        "sort": [{"filedAt": {"order": "desc"}}]
    }

    query_body_alt = {
        "query": f"ticker:{ticker} AND formType:(10-K OR 10-Q OR 8-K)",
        "from": 0,
        "size": size
    }

    headers_list = [
        {"Authorization": API_KEY, "Content-Type": "application/json"},
        {"x-api-key": API_KEY, "Content-Type": "application/json"},
        {"Authorization": API_KEY, "Accept": "application/json"},
    ]

    last_errs = []

    for base in ENDPOINT_CANDIDATES:
        for headers in headers_list:
            resp = _try_post(base, query_body_queryapi, headers)
            if isinstance(resp, Exception):
                last_errs.append((base, headers, str(resp)))
                continue

            if resp.status_code == 200:
                try:
                    data = resp.json()
                    if isinstance(data, dict):
                        if "filings" in data:
                            return data.get("filings", [])
                        if "data" in data and isinstance(data["data"], list):
                            return data["data"]
                        if "hits" in data and isinstance(data["hits"], list):
                            return data["hits"]
                    if isinstance(data, list):
                        return data
                    return []
                except Exception as e:
                    last_errs.append((base, headers, f"JSON parse error: {e}; resp_text={resp.text[:400]}"))
                    continue

            if resp.status_code in (401, 403):
                last_errs.append((base, headers, f"{resp.status_code} {resp.reason}; {resp.text[:400]}"))
                continue

            if resp.status_code == 404:
                try:
                    resp2 = requests.post(base, json=query_body_queryapi, params={"token": API_KEY}, timeout=30)
                    if resp2.status_code == 200:
                        try:
                            data = resp2.json()
                            if "filings" in data:
                                return data.get("filings", [])
                            if isinstance(data, list):
                                return data
                            return []
                        except Exception as e:
                            last_errs.append((base + " ?token", headers, f"JSON parse error: {e}; resp_text={resp2.text[:400]}"))
                            continue
                    else:
                        last_errs.append((base + " ?token", headers, f"{resp2.status_code} {resp2.text[:400]}"))
                except Exception as e:
                    last_errs.append((base + " ?token", headers, str(e)))

            resp_alt = _try_post(base, query_body_alt, headers)
            if isinstance(resp_alt, Exception):
                last_errs.append((base + " alt", headers, str(resp_alt)))
                continue

            if resp_alt.status_code == 200:
                try:
                    data = resp_alt.json()
                    if isinstance(data, dict) and "filings" in data:
                        return data.get("filings", [])
                    if isinstance(data, list):
                        return data
                    return []
                except Exception as e:
                    last_errs.append((base + " alt", headers, f"JSON parse error: {e}; resp_text={resp_alt.text[:400]}"))
                    continue

            last_errs.append((base, headers, f"{resp.status_code} {resp.reason}; {resp.text[:400]}"))

    debug_lines = []
    for rec in last_errs[-8:]:
        debug_lines.append(f"endpoint={rec[0]} headers={rec[1]} err={rec[2]}")
    raise RuntimeError("All endpoint attempts failed. Recent errors:\n" + "\n".join(debug_lines))


# -----------------------------
# Save + logging helpers
# -----------------------------
def save_filing(ticker: str, filing: dict) -> dict:
    form = filing.get("formType", "UNKNOWN")
    filed_at = filing.get("filedAt", "")[:10] or "unknown_date"

    folder = os.path.join("data", "raw", "filings", ticker)
    os.makedirs(folder, exist_ok=True)

    json_filename = f"{form}_{filed_at}.json"
    json_path = os.path.join(folder, json_filename)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(filing, f, indent=2)

    html_url = filing.get("linkToHtml") or filing.get("htmlUrl") or filing.get("url")
    html_path = None

    if html_url:
        try:
            html_headers = {
                "User-Agent": "FinGuard AI Bot (contact: daksh@example.com)",
                "Accept-Encoding": "gzip, deflate",
                "Host": "www.sec.gov"
            }

            r = requests.get(html_url, headers=html_headers, timeout=15)

            if r.status_code == 200:
                html_filename = f"{form}_{filed_at}.html"
                html_path = os.path.join(folder, html_filename)
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(r.text)
            else:
                print(f"  ⚠️ HTML download returned {r.status_code} for {ticker} - {html_url}")

        except Exception as e:
            print(f"  ⚠️ HTML fetch failed for {ticker}: {e}")

    return {
        "ticker": ticker,
        "form": form,
        "filed_at": filed_at,
        "url": html_url,
        "json_path": json_path,
        "html_path": html_path
    }


def append_log(rows: List[dict]):
    log_path = os.path.join("logs", "filings_log.csv")
    df = pd.DataFrame(rows)

    if os.path.exists(log_path):
        try:
            old = pd.read_csv(log_path)
            df = pd.concat([old, df], ignore_index=True)
        except Exception as e:
            print(f"Warning: failed reading existing log: {e}")

    os.makedirs("logs", exist_ok=True)
    df.to_csv(log_path, index=False)


# -----------------------------
# MAIN
# -----------------------------
def main():
    csv_path = os.path.join("data", "reference", "company_master.csv")
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"{csv_path} not found. Run from project root.")

    df = pd.read_csv(csv_path)
    ticker_col = detect_ticker_column(df)
    tickers = df[ticker_col].dropna().astype(str).str.strip().tolist()

    print(f"Loaded {len(tickers)} tickers from column: {ticker_col}")

    # ---------------------------------------------------------
    # >>> PRIORITY FILTER ADDED (top 100 tickers only)
    # ---------------------------------------------------------
    priority_100 = [
        "AAPL","MSFT","GOOG","GOOGL","AMZN","META","NVDA","TSLA","AMD","INTC",
        "NFLX","ADBE","PYPL","CRM","CSCO","ORCL","IBM","QCOM","AVGO","SHOP",
        "UBER","LYFT","SQ","MS","GS","JPM","BAC","WFC","V","MA",
        "KO","PEP","WMT","COST","HD","LOW","TGT","PG","JNJ","PFE",
        "MRNA","UNH","CVS","DIS","CMCSA","SPOT","NKE","SBUX","MCD","BKNG",
        "TSM","ASML","SAP","SONY","SPGI","INTU","ADP","TXN","AMAT","LRCX",
        "MU","ZM","SNOW","NET","PLTR","TWLO","DDOG","ZS","PANW","CRWD",
        "ROKU","ABNB","EBAY","BIDU","BABA","JD","TCEHY","ETSY","DOCU","FSLY",
        "T","VZ","TMUS","UPS","FDX","CAT","XOM","CVX","SHEL",
        "BRK.B","BRK.A","BLK","DE","NEE","SO","DUK","GE","RTX","LMT"
    ]

    tickers = [t for t in tickers if t in priority_100]

    print(f"Priority mode enabled: running only {len(tickers)} tickers.")
    # ---------------------------------------------------------

    logs = []

    for i, ticker in enumerate(tickers, start=1):
        print(f"[{i}/{len(tickers)}] Fetching: {ticker}")
        try:
            filings = fetch_filings_with_fallback(ticker, size=10)
            if not filings:
                print(f"  → No filings found for {ticker}")
            for f in filings:
                meta = save_filing(ticker, f)
                logs.append(meta)
        except Exception as e:
            print(f"❌ Error for {ticker}: {e}")
        time.sleep(PAUSE)

    if logs:
        append_log(logs)
        print(f"Saved {len(logs)} filing records; log updated.")
    else:
        print("No filings saved; no log updated.")

    print("Done.")

if __name__ == "__main__":
    main()
