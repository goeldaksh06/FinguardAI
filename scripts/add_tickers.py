"""Add a new batch of tickers to the market data pipeline without touching the existing
company_master.csv-driven scripts (market_prices.py/val_market_prices.py/generate_indicators.py)
or the (separately known-broken, see CLAUDE.md) company_master.csv itself.

Runs the same three stages those scripts do — fetch raw OHLCV via yfinance, clean/validate,
compute RSI/MACD/volatility indicators — for an explicit ticker list, and writes into the exact
same output directories the backend already reads from
(data/raw/market/prices/, data/processed/market/prices/, data/processed/market/indicators/).
Once run, new tickers work in /api/stock-risk, /api/watchlist-risk, /api/risk-trend with zero
backend changes, since those endpoints just list files in the indicators directory.

Usage:
    venv/Scripts/python.exe scripts/add_tickers.py --tickers RELIANCE.NS,TCS.NS
    venv/Scripts/python.exe scripts/add_tickers.py --nifty50
"""
import argparse
import os
import time

import numpy as np
import pandas as pd
import yfinance as yf

RAW_DIR = "data/raw/market/prices"
PROCESSED_PRICES_DIR = "data/processed/market/prices"
INDICATORS_DIR = "data/processed/market/indicators"

# NIFTY 50 constituents as of this session — India's 50 largest NSE-listed companies by free-float
# market cap. Hardcoded the same way scripts/sec_filings.py hardcodes its US priority-100 list;
# NIFTY 50 membership changes rarely enough that this doesn't need a live lookup for a first pass.
NIFTY_50 = [
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "HINDUNILVR", "ITC", "SBIN",
    "BHARTIARTL", "KOTAKBANK", "LT", "AXISBANK", "BAJFINANCE", "ASIANPAINT", "MARUTI",
    "HCLTECH", "SUNPHARMA", "TITAN", "ULTRACEMCO", "WIPRO", "NESTLEIND", "ONGC", "NTPC",
    "POWERGRID", "M&M", "TATASTEEL", "TATAMOTORS", "ADANIENT", "ADANIPORTS", "COALINDIA",
    "BAJAJFINSV", "HDFCLIFE", "SBILIFE", "GRASIM", "JSWSTEEL", "TECHM", "INDUSINDBK",
    "CIPLA", "DRREDDY", "EICHERMOT", "APOLLOHOSP", "BRITANNIA", "DIVISLAB", "HEROMOTOCO",
    "BAJAJ-AUTO", "UPL", "BPCL", "SHRIRAMFIN", "LTIM", "HINDALCO",
]


def fetch_raw(ticker: str) -> bool:
    try:
        hist = yf.Ticker(ticker).history(period="5y", interval="1d", auto_adjust=False)
        if hist.empty:
            print(f"  no price data for {ticker}")
            return False
        hist.reset_index(inplace=True)
        hist.to_csv(os.path.join(RAW_DIR, f"{ticker}.csv"), index=False)
        return True
    except Exception as e:
        print(f"  fetch error for {ticker}: {e}")
        return False


def clean(ticker: str) -> bool:
    required_cols = ["Date", "Open", "High", "Low", "Close", "Volume"]
    path = os.path.join(RAW_DIR, f"{ticker}.csv")
    try:
        df = pd.read_csv(path)
        if not all(c in df.columns for c in required_cols):
            print(f"  invalid columns for {ticker}")
            return False
        df = df[required_cols]
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df.dropna().sort_values("Date").drop_duplicates(subset="Date")
        df.to_csv(os.path.join(PROCESSED_PRICES_DIR, f"{ticker}.csv"), index=False)
        return True
    except Exception as e:
        print(f"  clean error for {ticker}: {e}")
        return False


def compute_indicators(ticker: str) -> bool:
    path = os.path.join(PROCESSED_PRICES_DIR, f"{ticker}.csv")
    try:
        df = pd.read_csv(path)
        df["Date"] = pd.to_datetime(df["Date"], utc=True, errors="coerce")
        df = df.sort_values("Date")

        close = df["Close"]
        df["returns"] = close.pct_change()
        df["ema_20"] = close.ewm(span=20).mean()
        df["ema_50"] = close.ewm(span=50).mean()

        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()
        rs = avg_gain / avg_loss
        df["rsi_14"] = 100 - (100 / (1 + rs))

        ema_12 = close.ewm(span=12).mean()
        ema_26 = close.ewm(span=26).mean()
        df["macd"] = ema_12 - ema_26
        df["macd_signal"] = df["macd"].ewm(span=9).mean()

        df["volatility_20"] = df["returns"].rolling(20).std()
        df = df.dropna()

        df.to_csv(os.path.join(INDICATORS_DIR, f"{ticker}.csv"), index=False)
        return True
    except Exception as e:
        print(f"  indicator error for {ticker}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", type=str, default=None, help="Comma-separated tickers")
    parser.add_argument("--nifty50", action="store_true", help="Use the hardcoded NIFTY 50 list (.NS suffix)")
    args = parser.parse_args()

    if args.nifty50:
        tickers = [f"{t}.NS" for t in NIFTY_50]
    elif args.tickers:
        tickers = [t.strip() for t in args.tickers.split(",")]
    else:
        parser.error("Pass --tickers or --nifty50")

    for d in (RAW_DIR, PROCESSED_PRICES_DIR, INDICATORS_DIR):
        os.makedirs(d, exist_ok=True)

    ok, failed = 0, []
    for i, ticker in enumerate(tickers, 1):
        print(f"[{i}/{len(tickers)}] {ticker}")
        if fetch_raw(ticker) and clean(ticker) and compute_indicators(ticker):
            ok += 1
            print("  done")
        else:
            failed.append(ticker)
        time.sleep(0.3)

    print(f"\nDone. {ok}/{len(tickers)} succeeded.")
    if failed:
        print(f"Failed: {failed}")


if __name__ == "__main__":
    main()
