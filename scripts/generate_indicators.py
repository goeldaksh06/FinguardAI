import os
import pandas as pd
import numpy as np

IN_DIR = "data/processed/market/prices"
OUT_DIR = "data/processed/market/indicators"

os.makedirs(OUT_DIR, exist_ok=True)

files = [f for f in os.listdir(IN_DIR) if f.endswith(".csv")]

print(f"📊 Generating indicators for {len(files)} tickers")

for i, file in enumerate(files, start=1):
    ticker = file.replace(".csv", "")
    path = os.path.join(IN_DIR, file)

    print(f"[{i}/{len(files)}] {ticker}")

    try:
        df = pd.read_csv(path)
        df["Date"] = pd.to_datetime(df["Date"], utc=True, errors="coerce")
        df = df.sort_values("Date")

        close = df["Close"]

        # Returns
        df["returns"] = close.pct_change()

        # EMA
        df["ema_20"] = close.ewm(span=20).mean()
        df["ema_50"] = close.ewm(span=50).mean()

        # RSI (14)
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()
        rs = avg_gain / avg_loss
        df["rsi_14"] = 100 - (100 / (1 + rs))

        # MACD
        ema_12 = close.ewm(span=12).mean()
        ema_26 = close.ewm(span=26).mean()
        df["macd"] = ema_12 - ema_26
        df["macd_signal"] = df["macd"].ewm(span=9).mean()

        # Volatility (20-day)
        df["volatility_20"] = df["returns"].rolling(20).std()

        df = df.dropna()

        out_path = os.path.join(OUT_DIR, file)
        df.to_csv(out_path, index=False)

        print("  ✔ Saved indicators")

    except Exception as e:
        print(f"  ❌ Error {ticker}: {e}")

print("✅ STEP 5.3 COMPLETE — Indicators generated.")

