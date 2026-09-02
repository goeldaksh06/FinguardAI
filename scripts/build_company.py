import requests
import pandas as pd
import yfinance as yf
import time
import os
from tqdm import tqdm
from config_loader import get_api_keys

api_keys = get_api_keys()
fmp_key = api_keys.get("fmp_api_key", "")
USER_AGENT = "FinGuardAI/1.0 (daksh@finguard.ai)"

os.makedirs("data/reference", exist_ok=True)
output_path = "data/reference/company_master.csv"

# ---------------- STEP 1: SEC base list ----------------
print("📊 Fetching SEC base company list...")
sec_url = "https://www.sec.gov/files/company_tickers.json"
resp = requests.get(sec_url, headers={"User-Agent": USER_AGENT}, timeout=30)
resp.raise_for_status()
sec_data = resp.json()
sec_df = pd.DataFrame.from_dict(sec_data, orient='index')
sec_df.rename(columns={'cik_str': 'cik', 'title': 'company_name'}, inplace=True)
sec_df["cik"] = sec_df["cik"].astype(str).str.zfill(10)
sec_df = sec_df.reset_index().rename(columns={"index": "ticker"})
print(f"✅ SEC companies loaded: {len(sec_df)}")

# ---------------- STEP 2: Try to enrich from FMP ----------------
print("📈 Attempting enrichment via FMP profile endpoint (may be rate-limited)...")
enriched = []
LIMIT = 1000
stop_due_to_403 = False

for ticker in tqdm(sec_df["ticker"][:LIMIT]):
    t = str(ticker).upper().strip()
    t_alt = t.replace(".", "-")
    for candidate in (t, t_alt):
        try:
            url = f"https://financialmodelingprep.com/api/v3/profile/{candidate}?apikey={fmp_key}"
            r = requests.get(url, timeout=20)
            if r.status_code == 403:
                print(f"⚠️ FMP returned 403 for {candidate} — stopping FMP calls.")
                stop_due_to_403 = True
                break
            if r.status_code == 200:
                j = r.json()
                if isinstance(j, list) and len(j) > 0:
                    p = j[0]
                    enriched.append({
                        "ticker": ticker,
                        "company_name_fmp": p.get("companyName"),
                        "cik_fmp": p.get("cik"),
                        "isin": p.get("isin"),
                        "sector": p.get("sector"),
                        "industry": p.get("industry"),
                        "exchange": p.get("exchangeShortName")
                    })
                    break
        except Exception:
            pass
    if stop_due_to_403:
        break
    time.sleep(0.25)

fmp_df = pd.DataFrame(enriched)
print(f"✅ FMP profiles retrieved: {len(fmp_df)}")

# ---------------- STEP 3: Merge SEC base with FMP results safely ----------------
print("🔗 Merging SEC base with FMP results...")
merged = pd.merge(sec_df, fmp_df, on="ticker", how="left") if "ticker" in fmp_df.columns else sec_df.copy()

# Guarantee these columns exist even if FMP failed
for col in ["company_name_fmp", "cik_fmp", "isin", "sector", "industry", "exchange"]:
    if col not in merged.columns:
        merged[col] = pd.NA

# Add fallback company_name_final column
merged["company_name_final"] = merged["company_name"].fillna(merged["company_name_fmp"])

# ---------------- STEP 4: Fill missing sector/industry via Yahoo ----------------
print("🌍 Filling missing sector/industry using yfinance (this may take 15–20 min)...")
for i, row in tqdm(merged.iterrows(), total=len(merged)):
    if pd.isna(row["sector"]) or pd.isna(row["industry"]):
        ticker = row["ticker"]
        try:
            info = yf.Ticker(ticker).info
            if isinstance(info, dict) and info:
                sector = info.get("sector")
                industry = info.get("industry")
                exchange = info.get("exchange")
                if sector and pd.isna(merged.at[i, "sector"]):
                    merged.at[i, "sector"] = sector
                if industry and pd.isna(merged.at[i, "industry"]):
                    merged.at[i, "industry"] = industry
                if exchange and pd.isna(merged.at[i, "exchange"]):
                    merged.at[i, "exchange"] = exchange
        except Exception:
            pass
        time.sleep(0.1)

# ---------------- STEP 5: Save final dataset ----------------
# make sure company_name_final exists even if previous steps failed to add it
if "company_name_final" not in merged.columns:
    merged["company_name_final"] = merged.get("company_name", pd.NA)

final_cols = ["ticker", "company_name_final", "cik", "isin", "sector", "industry", "exchange"]
if "cik_fmp" in merged.columns:
    merged["cik"] = merged["cik"].fillna(merged["cik_fmp"])

# rename and select columns safely
out_df = merged.copy()
for col in final_cols:
    if col not in out_df.columns:
        out_df[col] = pd.NA
out_df = out_df[final_cols]
out_df = out_df.rename(columns={"company_name_final": "company_name"})
out_df.drop_duplicates(subset=["ticker"], inplace=True)
out_df.to_csv(output_path, index=False)

print(f"💾 Saved company master table: {output_path}")
print(f"✅ Total companies in master file: {len(out_df)}")
