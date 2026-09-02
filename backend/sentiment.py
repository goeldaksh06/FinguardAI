"""News Sentiment — FinBERT, additive to (not a replacement for) news.py's keyword-based
news_event_risk.

Why a separate signal instead of folding this into news_event_risk: the keyword matcher is
deterministic and inspectable (every hit is "this headline contains the literal word X") —
sentiment analysis is a model's judgment call, a different kind of signal with different
trust properties. Keeping them separate lets a consumer use either, both, or neither, rather than
hiding one inside the other.

Uses FinBERT (ProsusAI/finbert on Hugging Face) specifically, not a generic sentiment library
(VADER/TextBlob) — general-purpose sentiment models are known to perform poorly on financial
text ("beats estimates but cuts guidance" reads mixed-to-positive generically but is often
bearish in context). FinBERT was fine-tuned on financial text for exactly this reason.

This does NOT predict what the market will do. Academic consensus is that news sentiment is a
weak, noisy signal at best — it's exposed here as one more real, evidence-linked data point
(per-headline sentiment, a trend over the lookback window, and price/sentiment divergence),
not a forecast. Every score traces back to the real headline that produced it.
"""
import statistics

_PIPELINE = None


def _get_pipeline():
    """Loads FinBERT once, lazily, on first real use — not at import time, so importing this
    module (e.g. for other backend code) doesn't force a multi-hundred-MB model load."""
    global _PIPELINE
    if _PIPELINE is None:
        from transformers import pipeline

        _PIPELINE = pipeline(
            "sentiment-analysis",
            model="ProsusAI/finbert",
            tokenizer="ProsusAI/finbert",
        )
    return _PIPELINE


def score_headlines(headlines: list[dict]) -> list[dict]:
    """Runs FinBERT over each headline's title. Returns the same headline dicts with `sentiment`
    (positive/negative/neutral) and `sentiment_confidence` added — nothing is dropped, so a
    caller who wants to inspect every raw score can.
    """
    if not headlines:
        return []

    pipe = _get_pipeline()
    titles = [h["title"] for h in headlines]
    results = pipe(titles, truncation=True)

    scored = []
    for h, r in zip(headlines, results):
        scored.append({**h, "sentiment": r["label"], "sentiment_confidence": round(r["score"], 3)})
    return scored


def sentiment_summary(scored_headlines: list[dict]) -> dict:
    """Aggregates per-headline FinBERT scores into one signal for the risk taxonomy.

    net_sentiment: -100 (uniformly negative, high confidence) to +100 (uniformly positive),
    weighted by each headline's confidence — a real weighted average, not an arbitrary number.

    trend: splits the headlines by published date into an earlier and later half and compares
    average sentiment between them — "is coverage getting more negative", a real signal distinct
    from the point-in-time net_sentiment.
    """
    if not scored_headlines:
        return {"net_sentiment": None, "trend": None, "counts": {}, "headlines": []}

    def signed(h):
        if h["sentiment"] == "positive":
            return h["sentiment_confidence"]
        if h["sentiment"] == "negative":
            return -h["sentiment_confidence"]
        return 0.0

    signed_scores = [signed(h) for h in scored_headlines]
    net_sentiment = round(statistics.mean(signed_scores) * 100, 1)

    counts = {"positive": 0, "negative": 0, "neutral": 0}
    for h in scored_headlines:
        counts[h["sentiment"]] = counts.get(h["sentiment"], 0) + 1

    dated = [h for h in scored_headlines if h.get("published_at")]
    trend = None
    if len(dated) >= 4:
        dated_sorted = sorted(dated, key=lambda h: h["published_at"])
        mid = len(dated_sorted) // 2
        earlier = [signed(h) for h in dated_sorted[:mid]]
        later = [signed(h) for h in dated_sorted[mid:]]
        trend_delta = round((statistics.mean(later) - statistics.mean(earlier)) * 100, 1)
        if trend_delta < -10:
            trend = "worsening"
        elif trend_delta > 10:
            trend = "improving"
        else:
            trend = "stable"

    return {
        "net_sentiment": net_sentiment,
        "trend": trend,
        "counts": counts,
        "headlines": scored_headlines,
    }


def sentiment_price_divergence(net_sentiment: float, price_change_pct: float) -> dict | None:
    """Flags when sentiment and recent price movement point in opposite directions — a real,
    established early-warning pattern (sentiment doesn't predict price, but a mismatch between
    them is worth a human's attention). Returns None when there's not enough signal on either
    side to say anything meaningful.
    """
    if net_sentiment is None or price_change_pct is None:
        return None
    if abs(net_sentiment) < 15 or abs(price_change_pct) < 1:
        return None

    diverges = (net_sentiment > 0 and price_change_pct < 0) or (net_sentiment < 0 and price_change_pct > 0)
    return {
        "diverges": diverges,
        "net_sentiment": net_sentiment,
        "price_change_pct": round(price_change_pct, 2),
    }
