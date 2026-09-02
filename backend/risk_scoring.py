"""Shared, deterministic risk-scoring formulas.

Pulled out of app.py so the same exact formula backs both the live /api/risk-taxonomy endpoint
and the historical backfill script (scripts/build_risk_history.py) — one source of truth, not two
copies that could silently drift apart.
"""


def stock_risk_score(row) -> tuple[float, list[str]]:
    """Rule-based risk score (0-100) from technical indicators, NOT a trained model.

    This is a simple, transparent weighted formula over RSI/MACD/volatility — unlike the fraud
    side, there is no ML model behind this. Kept deliberately explainable rather than trained,
    since there is no labeled "this stock was risky" dataset to train against.

    `row` needs rsi_14, macd, macd_signal, volatility_20, Close, ema_50 — works with a pandas
    Series (live use) or anything else supporting the same __getitem__ access (historical use).
    """
    reasons = []
    score = 0.0

    rsi = row["rsi_14"]
    if rsi >= 70:
        score += 30
        reasons.append(f"RSI overbought ({rsi:.1f})")
    elif rsi <= 30:
        score += 30
        reasons.append(f"RSI oversold ({rsi:.1f})")
    else:
        score += abs(rsi - 50) / 50 * 15

    macd_gap = row["macd"] - row["macd_signal"]
    if macd_gap < 0:
        score += min(abs(macd_gap) * 10, 25)
        reasons.append("MACD below signal (bearish momentum)")

    vol = row["volatility_20"]
    vol_component = min(vol * 400, 35)
    score += vol_component
    if vol_component > 15:
        reasons.append(f"Elevated 20-day volatility ({vol:.4f})")

    if row["Close"] < row["ema_50"]:
        score += 10
        reasons.append("Price below 50-day EMA")

    return round(min(score, 100), 2), reasons


def risk_label(score: float) -> str:
    if score >= 70:
        return "High Risk"
    if score >= 40:
        return "Elevated"
    if score >= 20:
        return "Moderate"
    return "Low Risk"
