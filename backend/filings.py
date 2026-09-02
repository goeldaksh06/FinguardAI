"""Company Filing Intelligence.

Reads the SEC filing metadata already collected by scripts/sec_filings.py
(data/raw/filings/<TICKER>/*.json) and, on demand, fetches the real filing document from SEC
EDGAR to extract specific sections (Risk Factors, MD&A) as plain text.

Design notes (why it works this way):
- The JSON files collected by sec_filings.py are metadata only (form type, filer, filed date,
  and a documentFormatFiles list of real document URLs). The .html files collected alongside them
  are SEC's *filing index* pages, not the filing text itself — confirmed by inspection, so this
  module does NOT try to parse those .html files for content.
- Section text is fetched live from the real document URL (documentFormatFiles[0].documentUrl)
  and extracted from the actual document body, not the table of contents. A 10-K/10-Q lists each
  Item heading twice (once in the TOC, once as the real section start) — extraction takes the
  *second* occurrence of the heading so it lands on the real section text, not the TOC line.
- Extracted text is cached to disk (data/processed/filings_cache/) since SEC EDGAR is a shared
  public resource — no reason to re-fetch and re-parse a filing that's already been read once.
- Every extracted section keeps its source metadata (ticker, form type, filed date, section name,
  document URL) so a claim can be traced back to the original filing, per the project's
  evidence-traceability goal.
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

BACKEND_DIR = os.path.dirname(__file__)
FILINGS_DIR = os.path.join(BACKEND_DIR, "..", "data", "raw", "filings")
CACHE_DIR = os.path.join(BACKEND_DIR, "..", "data", "processed", "filings_cache")

SEC_USER_AGENT = "FinGuard AI Research (contact: goeldaksh06@gmail.com)"

# (section name, start heading pattern, end heading pattern) — end is where the next Item begins.
SECTION_PATTERNS = {
    "risk_factors": (
        r"Item\s*1A\.?\s*Risk Factors",
        r"Item\s*1B\.?\s*Unresolved Staff Comments",
    ),
    "mdna": (
        r"Item\s*7\.?\s*Management",
        r"Item\s*7A\.?\s*Quantitative",
    ),
}


def _normalize_doc_url(url: str) -> str:
    """SEC's documentFormatFiles URLs point at the inline-XBRL *viewer*
    (https://www.sec.gov/ix?doc=/Archives/...), which returns a JS viewer shell, not the filing
    text. Strip that wrapper to get the raw, fetchable document URL underneath.
    """
    if not url:
        return url
    if "/ix?doc=" in url:
        path = url.split("/ix?doc=", 1)[1]
        return f"https://www.sec.gov{path}"
    return url


def list_filings(ticker: str) -> list[dict]:
    """Real filing metadata already collected for this ticker — form type, date, description,
    and a link to the actual SEC document (not the index page)."""
    folder = os.path.join(FILINGS_DIR, ticker.upper())
    if not os.path.isdir(folder):
        return []

    filings = []
    for fname in sorted(os.listdir(folder)):
        if not fname.endswith(".json"):
            continue
        with open(os.path.join(folder, fname), encoding="utf-8") as f:
            meta = json.load(f)
        doc_files = meta.get("documentFormatFiles") or []
        raw_doc_url = doc_files[0]["documentUrl"] if doc_files else meta.get("linkToHtml")
        primary_doc_url = _normalize_doc_url(raw_doc_url)
        filings.append(
            {
                "form_type": meta.get("formType"),
                "filed_at": meta.get("filedAt"),
                "description": meta.get("description"),
                "company_name": meta.get("companyName"),
                "document_url": primary_doc_url,
                "accession_no": meta.get("accessionNo"),
            }
        )
    filings.sort(key=lambda f: f["filed_at"] or "", reverse=True)
    return filings


# SEC's own official Form 8-K item-code definitions (see sec.gov's 8-K instructions) — these are
# a documented, public taxonomy, not something invented here. Each mapped code carries a weight
# reflecting how serious that disclosure category typically is, used to build one real,
# evidence-backed "governance/event risk" signal instead of a generic risk score.
_ITEM_CODE_WEIGHTS = {
    "1.03": (100, "Bankruptcy or receivership"),
    "5.04": (90, "Trading suspension"),
    "2.06": (35, "Material impairment"),
    "4.01": (35, "Change in certifying accountant"),
    "2.05": (30, "Costs from exit/disposal activities"),
    "5.02": (20, "Director/officer departure or appointment"),
    "2.03": (15, "Creation of a direct financial obligation"),
    "3.02": (10, "Unregistered sale of equity securities"),
}


def _score_eight_ks(eight_ks: list[dict], lookback_days: int, reference: datetime) -> dict:
    """Core scoring logic, factored out so scripts/build_risk_history.py can call it once per
    date without re-reading the ticker's filing metadata from disk on every call — list_filings()
    is only called once per ticker (by governance_risk_signal or directly), and this function is
    then reused across every historical date for that ticker.
    """
    if not eight_ks:
        return {"score": None, "reasons": [], "filings_considered": 0}

    cutoff = reference - timedelta(days=lookback_days)
    reasons = []
    total = 0.0
    considered = 0

    for f in eight_ks:
        filed_at = f.get("filed_at")
        if not filed_at:
            continue
        try:
            filed_dt = datetime.fromisoformat(filed_at)
        except ValueError:
            continue
        if filed_dt < cutoff or filed_dt > reference:
            continue
        considered += 1

        codes = re.findall(r"Item\s*(\d\.\d{2})", f.get("description") or "")
        for code in codes:
            if code in _ITEM_CODE_WEIGHTS:
                weight, label = _ITEM_CODE_WEIGHTS[code]
                total += weight
                reasons.append(
                    {
                        "label": label,
                        "item_code": code,
                        "filed_at": filed_at[:10],
                        "document_url": f["document_url"],
                    }
                )

    return {
        "score": round(min(total, 100), 1),
        "reasons": reasons,
        "filings_considered": considered,
    }


def governance_risk_signal(ticker: str, lookback_days: int = 365, as_of: datetime | None = None) -> dict:
    """Real, evidence-backed risk signal derived from 8-K item codes filed in the lookback
    window — not a fabricated score. Every contributing filing is named in `reasons` with a link
    back to the source document, per the project's evidence-traceability goal.

    `as_of` lets this be computed for a past date instead of "now" — a filing filed AFTER as_of
    is excluded, same as it would have been unknown to anyone standing at that point in time.

    Returns score=None (not a 0) when there's no 8-K data at all for this ticker, so "no data" is
    never confused with "no risk detected".
    """
    reference = as_of or datetime.now(timezone.utc)
    filings = list_filings(ticker)
    eight_ks = [f for f in filings if f["form_type"] == "8-K"]
    return _score_eight_ks(eight_ks, lookback_days, reference)


def _cache_path(ticker: str, accession_no: str, section: str) -> str:
    safe_accession = (accession_no or "unknown").replace("/", "-")
    return os.path.join(CACHE_DIR, f"{ticker.upper()}_{safe_accession}_{section}.json")


def _extract_section(full_text: str, start_pat: str, end_pat: str) -> str | None:
    starts = [m.start() for m in re.finditer(start_pat, full_text, re.IGNORECASE)]
    if len(starts) < 2:
        # Only found the TOC entry (or nothing) — no real section body to extract.
        return None
    start = starts[1]
    ends = [m.start() for m in re.finditer(end_pat, full_text, re.IGNORECASE) if m.start() > start]
    end = ends[0] if ends else start + 8000
    return full_text[start:end].strip()


def get_filing_section(ticker: str, accession_no: str, document_url: str, section: str) -> dict:
    """Fetch (or read cached) extracted section text for one filing.

    Raises ValueError if the section isn't found in the document (e.g. an 8-K has no Item 1A).
    """
    if section not in SECTION_PATTERNS:
        raise ValueError(f"Unknown section '{section}'. Valid: {list(SECTION_PATTERNS)}")

    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_file = _cache_path(ticker, accession_no, section)
    if os.path.exists(cache_file):
        with open(cache_file, encoding="utf-8") as f:
            return json.load(f)

    resp = requests.get(document_url, headers={"User-Agent": SEC_USER_AGENT}, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    full_text = re.sub(r"\n{2,}", "\n", soup.get_text(separator="\n"))

    start_pat, end_pat = SECTION_PATTERNS[section]
    extracted = _extract_section(full_text, start_pat, end_pat)
    if extracted is None:
        raise ValueError(f"Section '{section}' not found in this document")

    result = {
        "ticker": ticker.upper(),
        "section": section,
        "document_url": document_url,
        "text": extracted,
        "char_count": len(extracted),
    }
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(result, f)
    return result
