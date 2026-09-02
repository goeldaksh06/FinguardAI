"""News & Event Intelligence — Google News RSS.

Google News RSS needs no API key and no extra dependency (plain XML, parsed with the stdlib's
xml.etree). This module does NOT attempt sentiment analysis — there's no trained sentiment model
in this project, and fabricating one would violate the same honesty rule the SEC 8-K governance
signal follows. Instead, headlines are matched against a small, explicit keyword→risk-category
map (visible in _EVENT_KEYWORDS below) — a deterministic, inspectable rule, not a black-box score.
Every match keeps its real source, URL, and publish date, so a claim is always traceable to an
actual headline, not a fabricated "sentiment number".
"""
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

NEWS_USER_AGENT = "Mozilla/5.0 (FinGuard AI Research; contact: goeldaksh06@gmail.com)"

# Keyword -> (risk category label, weight). Deliberately small and literal rather than an NLP
# model — every hit is explainable ("this headline contains the word 'lawsuit'"), not a
# black-box sentiment score.
_EVENT_KEYWORDS = {
    "lawsuit": ("Legal", 20),
    "sues": ("Legal", 20),
    "sued": ("Legal", 20),
    "investigation": ("Regulatory", 25),
    "probe": ("Regulatory", 20),
    "recall": ("Operational", 25),
    "layoffs": ("Operational", 20),
    "layoff": ("Operational", 20),
    "data breach": ("Cybersecurity", 30),
    "hack": ("Cybersecurity", 25),
    "cyberattack": ("Cybersecurity", 30),
    "bankruptcy": ("Credit", 100),
    "downgrade": ("Market", 20),
    "guidance cut": ("Revenue", 30),
    "lowers guidance": ("Revenue", 30),
    "misses estimates": ("Revenue", 20),
    "supply chain": ("Supply Chain", 15),
    "shortage": ("Supply Chain", 15),
    "resigns": ("Management", 20),
    "steps down": ("Management", 20),
    "fined": ("Regulatory", 25),
    "antitrust": ("Regulatory", 25),
    "tariff": ("Geopolitical", 15),
    "sanctions": ("Geopolitical", 20),
}

_CACHE: dict[str, tuple[float, list[dict]]] = {}
_CACHE_TTL_SECONDS = 15 * 60


def fetch_headlines(query: str, max_items: int = 50) -> list[dict]:
    """Real headlines from Google News RSS for a search query. Cached in-process for
    _CACHE_TTL_SECONDS since repeated identical searches within a short window shouldn't
    re-hit Google on every API call."""
    now = time.time()
    cached = _CACHE.get(query)
    if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
        return cached[1]

    url = f"https://news.google.com/rss/search?q={requests.utils.quote(query)}&hl=en-US&gl=US&ceid=US:en"
    resp = requests.get(url, headers={"User-Agent": NEWS_USER_AGENT}, timeout=20)
    resp.raise_for_status()

    root = ET.fromstring(resp.text)
    headlines = []
    for item in root.findall(".//item")[:max_items]:
        title = item.findtext("title") or ""
        link = item.findtext("link") or ""
        pub_date = item.findtext("pubDate")
        source_el = item.find("source")
        source_name = source_el.text if source_el is not None else None

        published_at = None
        if pub_date:
            try:
                published_at = parsedate_to_datetime(pub_date).isoformat()
            except (TypeError, ValueError):
                published_at = None

        headlines.append(
            {"title": title, "url": link, "source": source_name, "published_at": published_at}
        )

    _CACHE[query] = (now, headlines)
    return headlines


def build_query(company_name: str | None, ticker: str) -> str:
    return f'"{company_name}" stock' if company_name else f"{ticker} stock"


def news_event_risk_signal(
    company_name: str, ticker: str, lookback_days: int = 14, headlines: list[dict] | None = None
) -> dict:
    """Keyword-matched event risk from real recent headlines. Returns score=None (not 0) when
    the news fetch itself fails or returns nothing, so a fetch failure is never confused with
    "no risk found". Pass `headlines` (e.g. from fetch_headlines()) to reuse an already-fetched
    set instead of fetching again — used so this and sentiment analysis score the identical
    headlines rather than two slightly different fetches.
    """
    if headlines is None:
        query = build_query(company_name, ticker)
        try:
            headlines = fetch_headlines(query)
        except requests.exceptions.RequestException:
            return {"score": None, "reasons": [], "articles_considered": 0, "error": "news fetch failed"}

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    total = 0.0
    reasons = []
    considered = 0

    for h in headlines:
        if h["published_at"]:
            try:
                pub_dt = datetime.fromisoformat(h["published_at"])
                if pub_dt < cutoff:
                    continue
            except ValueError:
                pass
        considered += 1

        title_lower = h["title"].lower()
        for keyword, (category, weight) in _EVENT_KEYWORDS.items():
            if keyword in title_lower:
                total += weight
                reasons.append(
                    {
                        "category": category,
                        "matched_keyword": keyword,
                        "headline": h["title"],
                        "source": h["source"],
                        "url": h["url"],
                        "published_at": h["published_at"],
                    }
                )

    return {
        "score": round(min(total, 100), 1) if headlines else None,
        "reasons": reasons,
        "articles_considered": considered,
    }
