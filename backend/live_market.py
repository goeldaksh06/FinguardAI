"""Live market data, computed on demand — replaces reliance on the static
data/processed/market/indicators/*.csv files, which were fetched once and never refreshed (found
stale by 250+ days for most of the ~9,749-ticker dataset during this session — see CLAUDE.md).

Fetches recent OHLCV directly from yfinance at request time and computes the exact same
indicators (EMA20/50, RSI14, MACD, 20-day volatility) that scripts/generate_indicators.py
computes offline, using the same formulas — so scores stay consistent with the historical
backfill's methodology, just computed fresh instead of read from a stale file.

Cached in-process with a short TTL so a watchlist with several tickers doesn't re-hit yfinance on
every single render, while still staying meaningfully current (worst case a few minutes stale,
not 8 months).
"""
import time

import numpy as np
import pandas as pd
import yfinance as yf

_CACHE_TTL_SECONDS = 10 * 60
_cache: dict[str, tuple[float, pd.DataFrame]] = {}


def _compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Same formulas as scripts/generate_indicators.py, applied to a freshly-fetched frame."""
    df = df.sort_values("Date").reset_index(drop=True)
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

    return df.dropna()


def fetch_live_indicators(ticker: str, period: str = "6mo") -> pd.DataFrame | None:
    """Live-fetched, freshly-computed indicator frame for a ticker, or None if the fetch failed
    or returned no usable data (invalid ticker, delisted, network error, etc.).
    """
    ticker = ticker.upper()
    now = time.time()
    cached = _cache.get(ticker)
    if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]

    try:
        hist = yf.Ticker(ticker).history(period=period, interval="1d", auto_adjust=False)
    except Exception:
        return None

    if hist is None or hist.empty:
        return None

    hist = hist.reset_index()
    hist = hist[["Date", "Open", "High", "Low", "Close", "Volume"]]
    df = _compute_indicators(hist)
    if df.empty:
        return None

    _cache[ticker] = (now, df)
    return df
