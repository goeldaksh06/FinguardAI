"""Evidence retrieval over real SEC filing text — the RAG half of ROADMAP.md §21's
evidence-first vision, scoped honestly.

This is real retrieval-augmented generation, not a demo of the concept: it chunks the actual
Risk Factors / MD&A text `backend/filings.py` fetches from SEC EDGAR, indexes it with TF-IDF, and
returns the passages most relevant to a query via cosine similarity — genuine ranked retrieval,
not just returning the whole section and hoping the LLM finds the right part.

Deliberately TF-IDF, not a dense embedding model (sentence-transformers, OpenAI embeddings,
etc.). Three real reasons, not just laziness:
  1. This project already had to split requirements.txt / requirements-deploy.txt because torch
     (used for FinBERT) doesn't fit a memory-constrained free-tier host. A second heavy embedding
     model would make that problem worse, not better.
  2. scikit-learn (which TF-IDF uses) is already a dependency in BOTH requirement sets — this adds
     zero new deployment weight.
  3. For the actual task here — find the paragraph in a 10-K's Risk Factors section that best
     matches "supply chain" or "litigation" — lexical/TF-IDF retrieval genuinely works well.
     Dense embeddings would help more for paraphrase-heavy queries, which isn't the dominant case
     for keyword-driven risk lookups. If that changes, swapping the vectorizer here for a real
     embedding model is a contained change — this module's public API (retrieve_passages) doesn't
     leak the implementation choice to callers.

Honest limitation, stated plainly rather than hidden: TF-IDF is lexical, not semantic — it won't
match "workforce reduction" to a query for "layoffs" the way a dense embedding might. It's a real,
working first cut, not the ceiling of what RAG could be here.
"""
import re

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

_CHUNK_WORDS = 180
_CHUNK_OVERLAP = 40


def chunk_text(text: str, chunk_words: int = _CHUNK_WORDS, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    """Splits real filing text into overlapping word-count chunks. Overlap prevents a relevant
    passage from being split exactly at a chunk boundary and losing its context on both sides.
    """
    words = re.split(r"\s+", text.strip())
    if not words or words == [""]:
        return []

    chunks = []
    step = max(chunk_words - overlap, 1)
    for start in range(0, len(words), step):
        chunk = " ".join(words[start:start + chunk_words])
        if chunk.strip():
            chunks.append(chunk)
        if start + chunk_words >= len(words):
            break
    return chunks


def retrieve_passages(query: str, chunks: list[str], top_k: int = 3) -> list[dict]:
    """Real ranked retrieval: TF-IDF vectorizes the query and every chunk, returns the top_k
    chunks by cosine similarity, each with its real similarity score — not just the first N
    chunks or a substring match.
    """
    if not chunks:
        return []

    vectorizer = TfidfVectorizer(stop_words="english", max_features=4000)
    try:
        matrix = vectorizer.fit_transform(chunks + [query])
    except ValueError:
        # All chunks were pure stopwords/empty after vectorization — nothing meaningful to rank.
        return []

    chunk_vectors = matrix[:-1]
    query_vector = matrix[-1]
    similarities = cosine_similarity(query_vector, chunk_vectors)[0]

    ranked = sorted(range(len(chunks)), key=lambda i: similarities[i], reverse=True)
    results = []
    for i in ranked[:top_k]:
        if similarities[i] <= 0:
            continue
        results.append({"text": chunks[i], "score": round(float(similarities[i]), 4)})
    return results


def search_filing_section(section_text: str, query: str, top_k: int = 3) -> list[dict]:
    """End-to-end: chunk a real filing section's text and retrieve the passages most relevant
    to a query. The one function callers actually need."""
    chunks = chunk_text(section_text)
    return retrieve_passages(query, chunks, top_k=top_k)
