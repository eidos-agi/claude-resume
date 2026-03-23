"""BM25 scoring for session search.

Implements Okapi BM25 with summary-first ranking:
  - 60% weight: BM25 on AI-generated summaries (title + goal + what_was_done)
  - 25% weight: BM25 on raw conversation text
  - 15% weight: recency (exponential decay, 30-day half-life)

BM25 naturally handles:
  - Term saturation: 2000 mentions ≠ 2000x better than 1 mention
  - Inverse document frequency: rare terms ("helios") outweigh common terms ("refactor")
  - Document length normalization: long sessions don't dominate just by being long
"""

import math
import re
import time
from dataclasses import dataclass, field

# BM25 tuning parameters
K1 = 1.5   # term frequency saturation (higher = slower saturation)
B = 0.75   # length normalization (0 = no normalization, 1 = full)

# Signal weights (must sum to 1.0)
W_SUMMARY = 0.60
W_RAW = 0.25
W_RECENCY = 0.15

# Recency decay
HALF_LIFE_DAYS = 30
_LAMBDA = math.log(2) / (HALF_LIFE_DAYS * 86400)

# Stop words to skip in BM25 (common words that add noise)
_STOP_WORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "it", "was", "be", "are", "were",
    "been", "has", "had", "do", "did", "will", "would", "could", "should",
    "not", "no", "this", "that", "these", "those", "i", "you", "we", "he",
    "she", "they", "my", "your", "our", "his", "her", "its", "their",
})

_WORD_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase, extract words, remove stop words."""
    return [w for w in _WORD_RE.findall(text.lower()) if w not in _STOP_WORDS]


@dataclass
class CorpusStats:
    """Pre-computed corpus-level statistics for BM25 IDF calculation."""
    total_docs: int = 0
    # doc frequency: how many docs contain each term
    doc_freq_summary: dict[str, int] = field(default_factory=dict)
    doc_freq_raw: dict[str, int] = field(default_factory=dict)
    # average document lengths (in tokens)
    avg_len_summary: float = 1.0
    avg_len_raw: float = 1.0


def build_corpus_stats(cache_index: dict) -> CorpusStats:
    """Build corpus-level BM25 statistics from the cache index.

    This scans all cached sessions to compute:
    - Document frequency for each term (summary and raw text separately)
    - Average document lengths

    Should be called once per search, not per-document.
    """
    stats = CorpusStats()
    total_summary_len = 0
    total_raw_len = 0
    n_with_summary = 0
    n_with_raw = 0

    for sid, data in cache_index.items():
        stats.total_docs += 1

        # Summary text
        summary = data.get("summary")
        if isinstance(summary, dict):
            summary_text = " ".join(filter(None, [
                summary.get("title", ""),
                summary.get("goal", summary.get("objective", "")),
                summary.get("what_was_done", summary.get("progress", "")),
            ]))
            if summary_text.strip():
                tokens = tokenize(summary_text)
                total_summary_len += len(tokens)
                n_with_summary += 1
                seen = set(tokens)
                for t in seen:
                    stats.doc_freq_summary[t] = stats.doc_freq_summary.get(t, 0) + 1

        # Raw search text
        search_text = data.get("search_text", "")
        if search_text:
            tokens = tokenize(search_text)
            total_raw_len += len(tokens)
            n_with_raw += 1
            seen = set(tokens)
            for t in seen:
                stats.doc_freq_raw[t] = stats.doc_freq_raw.get(t, 0) + 1

    stats.avg_len_summary = total_summary_len / max(n_with_summary, 1)
    stats.avg_len_raw = total_raw_len / max(n_with_raw, 1)

    return stats


def _idf(term: str, doc_freq: dict[str, int], total_docs: int) -> float:
    """Compute IDF for a term. Uses the standard BM25 IDF formula."""
    df = doc_freq.get(term, 0)
    if df == 0:
        return 0.0
    # Standard BM25 IDF: log((N - df + 0.5) / (df + 0.5) + 1)
    return math.log((total_docs - df + 0.5) / (df + 0.5) + 1.0)


def _bm25_score(query_tokens: list[str], doc_text: str, doc_freq: dict[str, int],
                total_docs: int, avg_dl: float) -> float:
    """Compute BM25 score for a single document against a query."""
    doc_tokens = tokenize(doc_text)
    dl = len(doc_tokens)
    if dl == 0:
        return 0.0

    # Build term frequency map for this document
    tf_map: dict[str, int] = {}
    for t in doc_tokens:
        tf_map[t] = tf_map.get(t, 0) + 1

    score = 0.0
    for qt in query_tokens:
        tf = tf_map.get(qt, 0)
        if tf == 0:
            continue
        idf = _idf(qt, doc_freq, total_docs)
        # BM25 TF component with length normalization
        numerator = tf * (K1 + 1)
        denominator = tf + K1 * (1 - B + B * dl / avg_dl)
        score += idf * numerator / denominator

    return score


def score_session(query_tokens: list[str], cached_data: dict | None,
                  raw_term_count: int, raw_text_len: int,
                  mtime: float, corpus: CorpusStats) -> tuple[float, float, float, float]:
    """Score a single session using BM25 summary + BM25 raw + recency.

    Returns (final_score, summary_score, raw_score, recency_score) for
    transparency/debugging.
    """
    # --- Summary BM25 ---
    summary_score = 0.0
    if cached_data:
        summary = cached_data.get("summary")
        if isinstance(summary, dict):
            summary_text = " ".join(filter(None, [
                summary.get("title", ""),
                summary.get("goal", summary.get("objective", "")),
                summary.get("what_was_done", summary.get("progress", "")),
            ]))
            if summary_text.strip():
                summary_score = _bm25_score(
                    query_tokens, summary_text,
                    corpus.doc_freq_summary, corpus.total_docs,
                    corpus.avg_len_summary,
                )

    # --- Raw text BM25 ---
    # We approximate BM25 from pre-counted term frequencies to avoid
    # re-tokenizing the full raw text (which may be 1-5MB).
    raw_score = 0.0
    if raw_term_count > 0 and corpus.total_docs > 0:
        # Approximate: treat each query token as having equal share of total_count
        n_terms = len(query_tokens) if query_tokens else 1
        avg_tf_per_term = raw_term_count / n_terms
        # Approximate doc length in tokens (~5 chars per token)
        approx_dl = raw_text_len / 5.0
        avg_dl = corpus.avg_len_raw

        for qt in query_tokens:
            idf = _idf(qt, corpus.doc_freq_raw, corpus.total_docs)
            tf = avg_tf_per_term  # approximation
            numerator = tf * (K1 + 1)
            denominator = tf + K1 * (1 - B + B * approx_dl / max(avg_dl, 1))
            raw_score += idf * numerator / denominator

    # --- Recency ---
    age_s = max(time.time() - mtime, 0)
    recency_score = math.exp(-_LAMBDA * age_s)

    # --- Combine with weights ---
    # Normalize BM25 scores to roughly 0-1 range for fair weighting.
    # We use a sigmoid-like squash: score / (score + k) which maps [0,∞) to [0,1)
    _SQUASH_K_SUMMARY = 3.0  # expected "good" summary BM25 score
    _SQUASH_K_RAW = 5.0      # expected "good" raw BM25 score

    norm_summary = summary_score / (summary_score + _SQUASH_K_SUMMARY) if summary_score > 0 else 0.0
    norm_raw = raw_score / (raw_score + _SQUASH_K_RAW) if raw_score > 0 else 0.0

    final = (
        W_SUMMARY * norm_summary +
        W_RAW * norm_raw +
        W_RECENCY * recency_score
    )

    # Scale to 0-100 for readability
    final_100 = round(final * 100, 1)

    return final_100, round(summary_score, 3), round(raw_score, 3), round(recency_score, 3)
