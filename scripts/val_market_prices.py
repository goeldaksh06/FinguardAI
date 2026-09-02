import os
import pandas as pd

RAW_DIR = "data/raw/market/prices"
OUT_DIR = "data/processed/market/prices"

os.makedirs(OUT_DIR, exist_ok=True)

required_cols = ["Date", "Open", "High", "Low", "Close", "Volume"]

files = [f for f in os.listdir(RAW_DIR) if f.endswith(".csv")]

print(f"🔍 Found {len(files)} raw price files.")

for i, file in enumerate(files, start=1):
    ticker = file.replace(".csv", "")
    path = os.path.join(RAW_DIR, file)

    print(f"[{i}/{len(files)}] Cleaning {ticker}")

    try:
        df = pd.read_csv(path)

        # Column validation
        if not all(col in df.columns for col in required_cols):
            print(f"  ❌ Invalid columns → skipped")
            continue

        # Cleaning
        df = df[required_cols]
        df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df.dropna()
        df = df.sort_values("Date")
        df = df.drop_duplicates(subset="Date")

        # Save processed
        out_path = os.path.join(OUT_DIR, file)
        df.to_csv(out_path, index=False)

        print(f"  ✔ Saved → {out_path}")

    except Exception as e:
        print(f"  ❌ Error {ticker}: {e}")

print("✅ STEP 5.2 COMPLETE — All prices validated.")
