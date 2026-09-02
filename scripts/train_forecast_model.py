"""First real Forecasting Agent baseline — trains a walk-forward-validated model that predicts
whether a ticker's market_risk will rise materially over the next 30 trading days.

Per ROADMAP.md Rule 13 ("LLMs reason and communicate; they do not predict numbers") and
docs/roadmap.md's own recommendation: this is real, traditional ML (XGBoost), not an LLM guess.

Scope deliberately narrow for this first cut, per the honesty note already in CLAUDE.md:
"Only 149/1236 rows per ticker have reliable governance coverage, so an early model should
probably start with market_risk-only labels." So:
  - Label is defined ONLY on market_risk (available for all 133 tickers, no missing-data gaps).
  - Features are technical indicators (RSI/MACD/volatility/EMA spread/returns) plus the current
    market_risk itself — all live-computable at request time via backend/live_market.py, so the
    trained model can actually be served, not just evaluated offline.
  - governance_risk/news are NOT used as features in this first cut — they have coverage gaps
    (governance) or aren't in the historical backfill at all (news), and adding them now would
    mean the model silently degrades for any ticker/date without that data. A future iteration
    can add them once there's a plan for their missing-data pattern.

Target definition: label = 1 if market_risk at t+30 trading days is at least LABEL_THRESHOLD
points higher than market_risk at t, else 0. This is a real, inspectable, binary target — not
"predict the exact score," which would overclaim precision this data can't support.

Validation: walk-forward / chronological split (train < val < test by date), with a purge gap of
LOOKAHEAD_DAYS at each boundary so no training label's forward-looking window crosses into the
validation/test period's feature dates — the standard fix for the "boundary leakage" that a naive
chronological split still allows in a forward-looking-label setup.

Baseline comparison: a naive "always predict majority class" classifier, per ROADMAP.md's own
requirement ("A complex model must prove that it improves performance").
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parent.parent
RISK_HISTORY_DIR = ROOT / "data" / "processed" / "risk_history"
INDICATORS_DIR = ROOT / "data" / "processed" / "market" / "indicators"
MODEL_DIR = ROOT / "backend" / "model"

LOOKAHEAD_DAYS = 30
LABEL_THRESHOLD = 10.0

FEATURE_COLS = [
    "market_risk",
    "rsi_14",
    "macd",
    "macd_signal",
    "volatility_20",
    "returns",
    "ema_spread",
]

TRAIN_END = "2024-06-01"
VAL_END = "2025-01-01"
# test set is everything after VAL_END


def build_dataset() -> pd.DataFrame:
    """Merges risk_history (market_risk) with indicators (technical features) per ticker,
    builds the forward-looking label, and concatenates every ticker into one frame."""
    frames = []
    tickers = sorted(p.stem for p in RISK_HISTORY_DIR.glob("*.csv"))

    for ticker in tickers:
        rh_path = RISK_HISTORY_DIR / f"{ticker}.csv"
        ind_path = INDICATORS_DIR / f"{ticker}.csv"
        if not ind_path.exists():
            continue

        rh = pd.read_csv(rh_path, parse_dates=["date"])
        ind = pd.read_csv(ind_path, parse_dates=["Date"])
        ind["date"] = ind["Date"].dt.tz_localize(None).dt.normalize()
        ind["ema_spread"] = (ind["ema_20"] - ind["ema_50"]) / ind["ema_50"]

        merged = rh.merge(
            ind[["date", "rsi_14", "macd", "macd_signal", "volatility_20", "returns", "ema_spread"]],
            on="date",
            how="inner",
        )
        merged = merged.sort_values("date").reset_index(drop=True)

        merged["future_market_risk"] = merged["market_risk"].shift(-LOOKAHEAD_DAYS)
        merged["label"] = (
            merged["future_market_risk"] - merged["market_risk"] >= LABEL_THRESHOLD
        ).astype(int)
        merged = merged.dropna(subset=["future_market_risk"] + FEATURE_COLS)
        merged["ticker"] = ticker

        frames.append(merged[["ticker", "date"] + FEATURE_COLS + ["label"]])

    return pd.concat(frames, ignore_index=True)


def chronological_split(df: pd.DataFrame):
    """Chronological split with a LOOKAHEAD_DAYS purge gap at each boundary, so no training
    example's label (which looks LOOKAHEAD_DAYS into the future) draws on data from the
    validation/test period, and likewise for val→test."""
    train_end = pd.Timestamp(TRAIN_END)
    val_end = pd.Timestamp(VAL_END)
    purge = pd.Timedelta(days=LOOKAHEAD_DAYS * 1.5)  # trading days -> calendar-day margin

    train = df[df["date"] <= train_end - purge]
    val = df[(df["date"] > train_end + purge) & (df["date"] <= val_end - purge)]
    test = df[df["date"] > val_end + purge]
    return train, val, test


def evaluate(y_true, y_prob, y_pred, label: str) -> dict:
    return {
        "label": label,
        "n": int(len(y_true)),
        "positive_rate": round(float(np.mean(y_true)), 4),
        "precision": round(float(precision_score(y_true, y_pred, zero_division=0)), 4),
        "recall": round(float(recall_score(y_true, y_pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y_true, y_pred, zero_division=0)), 4),
        "roc_auc": round(float(roc_auc_score(y_true, y_prob)), 4) if len(set(y_true)) > 1 else None,
        "pr_auc": round(float(average_precision_score(y_true, y_prob)), 4) if len(set(y_true)) > 1 else None,
    }


def main():
    print("Building dataset from risk_history + indicators...")
    df = build_dataset()
    print(f"Total rows: {len(df)}, tickers: {df['ticker'].nunique()}, "
          f"date range: {df['date'].min().date()} to {df['date'].max().date()}")
    print(f"Overall positive rate (market_risk +{LABEL_THRESHOLD} within {LOOKAHEAD_DAYS}d): "
          f"{df['label'].mean():.4f}")

    train, val, test = chronological_split(df)
    print(f"Train: {len(train)} rows ({train['date'].min().date()}–{train['date'].max().date()})")
    print(f"Val:   {len(val)} rows ({val['date'].min().date()}–{val['date'].max().date()})")
    print(f"Test:  {len(test)} rows ({test['date'].min().date()}–{test['date'].max().date()})")

    X_train, y_train = train[FEATURE_COLS], train["label"]
    X_val, y_val = val[FEATURE_COLS], val["label"]
    X_test, y_test = test[FEATURE_COLS], test["label"]

    # Naive baseline: always predict the majority class from the training set.
    majority_class = int(y_train.mode()[0])
    naive_val_pred = np.full(len(y_val), majority_class)
    naive_val_prob = np.full(len(y_val), y_train.mean())
    naive_test_pred = np.full(len(y_test), majority_class)
    naive_test_prob = np.full(len(y_test), y_train.mean())

    naive_val_metrics = evaluate(y_val, naive_val_prob, naive_val_pred, "naive_baseline_val")
    naive_test_metrics = evaluate(y_test, naive_test_prob, naive_test_pred, "naive_baseline_test")

    scale_pos_weight = (y_train == 0).sum() / max((y_train == 1).sum(), 1)
    model = XGBClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        scale_pos_weight=scale_pos_weight,
        eval_metric="aucpr",
        random_state=42,
    )
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)

    val_prob = model.predict_proba(X_val)[:, 1]
    val_pred = (val_prob >= 0.5).astype(int)
    test_prob = model.predict_proba(X_test)[:, 1]
    test_pred = (test_prob >= 0.5).astype(int)

    model_val_metrics = evaluate(y_val, val_prob, val_pred, "xgboost_val")
    model_test_metrics = evaluate(y_test, test_prob, test_pred, "xgboost_test")

    importances = dict(zip(FEATURE_COLS, [round(float(x), 4) for x in model.feature_importances_]))

    print("\n--- Naive baseline (majority class) ---")
    print(json.dumps(naive_test_metrics, indent=2))
    print("\n--- XGBoost ---")
    print(json.dumps(model_test_metrics, indent=2))
    print("\nFeature importances:", json.dumps(importances, indent=2))

    MODEL_DIR.mkdir(exist_ok=True)
    import joblib
    joblib.dump(model, MODEL_DIR / "forecast_model.joblib")

    metrics = {
        "target_definition": (
            f"label=1 if market_risk rises by >= {LABEL_THRESHOLD} points over the next "
            f"{LOOKAHEAD_DAYS} trading days, else 0. market_risk-only label (no governance/news "
            f"dependency) so all 133 tickers' full history is usable, per the known governance-"
            f"coverage gap documented in CLAUDE.md."
        ),
        "features": FEATURE_COLS,
        "split": {
            "train_end": TRAIN_END,
            "val_end": VAL_END,
            "purge_gap_days": LOOKAHEAD_DAYS * 1.5,
        },
        "naive_baseline": {"val": naive_val_metrics, "test": naive_test_metrics},
        "xgboost": {"val": model_val_metrics, "test": model_test_metrics},
        "feature_importances": importances,
    }
    with open(MODEL_DIR / "forecast_metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"\nSaved model to {MODEL_DIR / 'forecast_model.joblib'}")
    print(f"Saved metrics to {MODEL_DIR / 'forecast_metrics.json'}")


if __name__ == "__main__":
    main()
