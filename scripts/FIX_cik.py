import pandas as pd

df = pd.read_csv("data/reference/company_master.csv")

# Move ISIN column into CIK if CIK is empty
df["cik"] = df["cik"].fillna(df["isin"])
df["cik"] = df["cik"].astype(str).str.zfill(10)

df.to_csv("data/reference/company_master_fixed.csv", index=False)

print("✔ FIXED FILE saved as company_master_fixed.csv")

