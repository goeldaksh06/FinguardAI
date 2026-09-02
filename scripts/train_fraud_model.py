"""Train the FinGuard AI fraud detection model on the mlg-ulb credit card fraud dataset."""
import os
import json

import joblib
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score, f1_score, classification_report
from xgboost import XGBClassifier

DATA_PATH = "data/raw/fraud/creditcard.csv"
MODEL_DIR = "backend/model"
MODEL_PATH = os.path.join(MODEL_DIR, "fraud_model.joblib")
METRICS_PATH = os.path.join(MODEL_DIR, "metrics.json")

os.makedirs(MODEL_DIR, exist_ok=True)

print(f"Loading dataset from {DATA_PATH}")
df = pd.read_csv(DATA_PATH)
print(f"Loaded {len(df)} rows, fraud cases: {df['Class'].sum()}")

# --------------------------------------------------
# Feature engineering (12+ transaction-based features)
# --------------------------------------------------
df["hour_of_day"] = (df["Time"] // 3600) % 24
df["amount_log"] = np.log1p(df["Amount"])
df["amount_zscore"] = (df["Amount"] - df["Amount"].mean()) / df["Amount"].std()

rolling_window = 5000
df["amount_rolling_mean"] = df["Amount"].rolling(rolling_window, min_periods=1).mean()
df["amount_rolling_std"] = df["Amount"].rolling(rolling_window, min_periods=1).std().fillna(0)
df["amount_deviation"] = df["Amount"] - df["amount_rolling_mean"]

df["is_night"] = df["hour_of_day"].apply(lambda h: 1 if (h < 6 or h >= 22) else 0)
df["v_sum_abs"] = df[[c for c in df.columns if c.startswith("V")]].abs().sum(axis=1)
df["v_mean"] = df[[c for c in df.columns if c.startswith("V")]].mean(axis=1)
df["amount_per_v_magnitude"] = df["Amount"] / (df["v_sum_abs"] + 1e-6)

feature_cols = [c for c in df.columns if c.startswith("V")] + [
    "Amount", "hour_of_day", "amount_log", "amount_zscore",
    "amount_rolling_mean", "amount_rolling_std", "amount_deviation",
    "is_night", "v_sum_abs", "v_mean", "amount_per_v_magnitude",
]

X = df[feature_cols]
y = df["Class"]

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, stratify=y, random_state=42
)

# --------------------------------------------------
# Class imbalance handling via scale_pos_weight
# --------------------------------------------------
neg, pos = (y_train == 0).sum(), (y_train == 1).sum()
scale_pos_weight = neg / pos
print(f"Train class balance -> neg: {neg}, pos: {pos}, scale_pos_weight: {scale_pos_weight:.1f}")

model = XGBClassifier(
    n_estimators=300,
    max_depth=5,
    learning_rate=0.05,
    subsample=0.9,
    colsample_bytree=0.9,
    scale_pos_weight=scale_pos_weight,
    eval_metric="aucpr",
    random_state=42,
    n_jobs=-1,
)

print("Training XGBoost classifier...")
model.fit(X_train, y_train)

y_proba = model.predict_proba(X_test)[:, 1]
y_pred = (y_proba >= 0.5).astype(int)

auc = roc_auc_score(y_test, y_proba)
f1 = f1_score(y_test, y_pred)

print(f"AUC-ROC: {auc:.4f}")
print(f"F1-score: {f1:.4f}")
print(classification_report(y_test, y_pred, digits=4))

joblib.dump({"model": model, "feature_cols": feature_cols}, MODEL_PATH)
with open(METRICS_PATH, "w") as f:
    json.dump({
        "auc_roc": round(auc, 4),
        "f1_score": round(f1, 4),
        "n_transactions": int(len(df)),
        "n_fraud": int(df["Class"].sum()),
        "n_features": len(feature_cols),
    }, f, indent=2)

print(f"Saved model to {MODEL_PATH}")
print(f"Saved metrics to {METRICS_PATH}")
