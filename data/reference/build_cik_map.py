import pandas as pd
import json

# Your cleaned file
df = pd.read_csv("data/reference/company_master.csv")

mapping = {}
for _, row in df.iterrows():
    ticker = str(row["ticker"]).upper().strip()
    cik = str(row["isin"]).zfill(10)   # your file has CIK in ISIN column
    mapping[ticker] = cik

with open("data/reference/cik_map.json", "w") as f:
    json.dump(mapping, f, indent=2)

print("✔ Local cik_map.json created with", len(mapping), "entries")
