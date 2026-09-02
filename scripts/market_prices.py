# scripts/market_prices.py

import os
import time
import pandas as pd
import yfinance as yf

# --------------------------------------------------
# Config
# --------------------------------------------------
DATA_DIR = "data/raw/market/prices"
COMPANY_FILE = "data/reference/company_master.csv"

os.makedirs(DATA_DIR, exist_ok=True)

# --------------------------------------------------
# Load tickers
# --------------------------------------------------
df = pd.read_csv(COMPANY_FILE)
tickers = (
    df["ticker"]
    .dropna()
    .astype(str)
    .str.upper()
    .str.strip()
    .unique()
    .tolist()
)

print(f"Loaded {len(tickers)} tickers.")

# --------------------------------------------------
# Download OHLCV per ticker
# --------------------------------------------------
for i, ticker in enumerate(tickers, start=1):
    print(f"[{i}/{len(tickers)}] Fetching {ticker}")

    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(
            period="5y",        
            interval="1d",
            auto_adjust=False
        )

        if hist.empty:
            print(f"  ⚠️ No price data for {ticker}")
            continue

        hist.reset_index(inplace=True)

        save_path = os.path.join(DATA_DIR, f"{ticker}.csv")
        hist.to_csv(save_path, index=False)

        print(f"  ✔ Saved {ticker} → {save_path}")

    except Exception as e:
        print(f"  ❌ Error for {ticker}: {e}")

    time.sleep(0.3)  