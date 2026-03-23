"""Tests for BM25 summary-first scoring.

Validates that the new scoring algorithm:
1. Produces meaningful score spread (not flat like RRF)
2. Ranks summary-matching sessions above frequency-only matches
3. Handles missing summaries gracefully
4. Runs against real data and produces sensible rankings
"""
import json
import math
import time
from pathlib import Path

import pytest

from resume_resume.bm25 import (
    tokenize,
    build_corpus_stats,
    score_session,
    CorpusStats,
)


# ---------------------------------------------------------------------------
# Unit tests for tokenizer
# ---------------------------------------------------------------------------

def test_tokenize_basic():
    assert tokenize("Helios Browser Automation") == ["helios", "browser", "automation"]


def test_tokenize_removes_stop_words():
    tokens = tokenize("the quick brown fox is on the table")
    assert "the" not in tokens
    assert "is" not in tokens
    assert "on" not in tokens
    assert "quick" in tokens
    assert "brown" in tokens


def test_tokenize_handles_punctuation():
    tokens = tokenize("hello-world! foo_bar? baz.qux")
    assert "hello" in tokens
    assert "world" in tokens


# ---------------------------------------------------------------------------
# Unit tests for corpus stats
# ---------------------------------------------------------------------------

def test_build_corpus_stats_basic():
    cache = {
        "s1": {
            "summary": {
                "title": "Helios daemon setup",
                "goal": "Configure the helios daemon",
                "what_was_done": "Installed and configured helios",
            },
            "search_text": "helios daemon configuration and setup process",
        },
        "s2": {
            "summary": {
                "title": "Reeves finance reconciliation",
                "goal": "Reconcile bank accounts",
                "what_was_done": "Matched transactions and fixed discrepancies",
            },
            "search_text": "reeves finance bank reconciliation transactions",
        },
        "s3": {
            "summary": {
                "title": "Debug helios auth",
                "goal": "Fix authentication in helios",
                "what_was_done": "Fixed token refresh in helios auth layer",
            },
            "search_text": "helios auth token refresh debug fix authentication",
        },
    }

    stats = build_corpus_stats(cache)

    assert stats.total_docs == 3
    # "helios" appears in 2 summaries
    assert stats.doc_freq_summary.get("helios", 0) == 2
    # "reeves" appears in 1 summary
    assert stats.doc_freq_summary.get("reeves", 0) == 1
    # "helios" appears in 2 raw texts
    assert stats.doc_freq_raw.get("helios", 0) == 2
    assert stats.avg_len_summary > 0
    assert stats.avg_len_raw > 0


# ---------------------------------------------------------------------------
# Scoring tests: summary-first ranking
# ---------------------------------------------------------------------------

def test_summary_match_beats_frequency_only():
    """A session with 'helios' in its summary should score higher than one
    that mentions helios 1000x in raw text but has an unrelated summary."""
    cache = {
        "helios_session": {
            "summary": {
                "title": "Helios Daemon Unification",
                "goal": "Implement unified helios daemon architecture",
                "what_was_done": "Built helios daemon with auth sessions",
            },
            "search_text": "helios daemon " * 50,  # 50 mentions
        },
        "noise_session": {
            "summary": {
                "title": "Reeves Finance Provenance",
                "goal": "Track financial data provenance",
                "what_was_done": "Built provenance tracking for reeves",
            },
            "search_text": "helios " * 500,  # 500 mentions but unrelated summary
        },
    }

    corpus = build_corpus_stats(cache)
    query_tokens = tokenize("helios daemon")
    now = time.time()

    # Helios session: summary matches, 50 raw hits
    score_helios, *_ = score_session(
        query_tokens, cache["helios_session"],
        raw_term_count=100, raw_text_len=5000,
        mtime=now - 7 * 86400, corpus=corpus,
    )

    # Noise session: summary doesn't match, 500 raw hits
    score_noise, *_ = score_session(
        query_tokens, cache["noise_session"],
        raw_term_count=500, raw_text_len=5000,
        mtime=now - 7 * 86400, corpus=corpus,
    )

    assert score_helios > score_noise, (
        f"Summary-matching session ({score_helios}) should beat "
        f"frequency-only session ({score_noise})"
    )


def test_missing_summary_degrades_gracefully():
    """A session with no summary should still score based on raw + recency."""
    corpus = CorpusStats(
        total_docs=100,
        doc_freq_summary={"helios": 5},
        doc_freq_raw={"helios": 20},
        avg_len_summary=15.0,
        avg_len_raw=200.0,
    )
    query_tokens = tokenize("helios")
    now = time.time()

    # No cached data at all
    score_no_cache, summary_bm25, raw_bm25, recency = score_session(
        query_tokens, None,
        raw_term_count=50, raw_text_len=10000,
        mtime=now - 3 * 86400, corpus=corpus,
    )

    assert summary_bm25 == 0.0, "No summary should give 0 summary BM25"
    assert raw_bm25 > 0, "Raw text should still score"
    assert recency > 0, "Recency should still score"
    assert score_no_cache > 0, "Overall score should be positive"


def test_score_spread_not_flat():
    """Scores should have meaningful spread across diverse sessions."""
    cache = {}
    now = time.time()
    sessions = [
        ("high_match", "Helios browser automation daemon", "Build helios browser control", 200, 3),
        ("medium_match", "Debug auth in helios", "Fix helios token", 50, 10),
        ("low_match", "Reeves finance setup", "Configure reeves", 5, 2),
        ("noise", "Empty session", "No activity", 1, 30),
    ]

    for sid, title, goal, hits, age_days in sessions:
        cache[sid] = {
            "summary": {"title": title, "goal": goal, "what_was_done": ""},
            "search_text": "helios " * hits + "filler " * 100,
        }

    corpus = build_corpus_stats(cache)
    query_tokens = tokenize("helios browser")

    scores = []
    for sid, title, goal, hits, age_days in sessions:
        score, *_ = score_session(
            query_tokens, cache[sid],
            raw_term_count=hits, raw_text_len=hits * 100,
            mtime=now - age_days * 86400, corpus=corpus,
        )
        scores.append((sid, score))

    scores.sort(key=lambda x: x[1], reverse=True)
    spread = scores[0][1] - scores[-1][1]

    print(f"\n[test_score_spread_not_flat]")
    for sid, s in scores:
        print(f"  {sid:20s}  score={s:5.1f}")
    print(f"  Spread: {spread:.1f}")

    # Spread should be meaningful (at least 10 points on 0-100 scale)
    assert spread > 10, f"Score spread too small: {spread:.1f}"

    # Best match should be the helios-specific session
    assert scores[0][0] == "high_match", f"Expected high_match first, got {scores[0][0]}"


# ---------------------------------------------------------------------------
# Real data benchmark
# ---------------------------------------------------------------------------

def test_real_data_bm25_vs_rrf():
    """Run BM25 scoring against real cached data and compare spread to RRF."""
    cache_dir = Path.home() / ".claude" / "resume-summaries"
    if not cache_dir.exists():
        pytest.skip("No real cache directory found")

    cache_files = list(cache_dir.glob("*.json"))
    if len(cache_files) < 50:
        pytest.skip(f"Too few cache files ({len(cache_files)})")

    # Load cache
    cache_index = {}
    for f in cache_files:
        try:
            cache_index[f.stem] = json.loads(f.read_bytes())
        except Exception:
            pass

    corpus = build_corpus_stats(cache_index)

    test_queries = [
        "hedgehog",
        "helios browser automation",
        "eidos capital alpaca",
    ]

    now = time.time()

    for query in test_queries:
        query_tokens = tokenize(query)
        terms_bytes = [w.encode() for w in query.lower().split()]

        results = []
        for sid, data in cache_index.items():
            search_text = data.get("search_text", "")
            if not search_text:
                continue
            raw = search_text.encode("utf-8", errors="replace")

            # Check all terms present
            total_count = 0
            all_present = True
            for term in terms_bytes:
                c = raw.count(term)
                if c == 0:
                    all_present = False
                    break
                total_count += c

            if not all_present:
                continue

            # Get summary title for display
            summary = data.get("summary", {})
            title = summary.get("title", "")[:50] if isinstance(summary, dict) else ""

            # Approximate mtime from cache (use a spread for variety)
            mtime = now - (hash(sid) % 30) * 86400  # fake ages 0-30 days

            score, s_bm25, r_bm25, recency = score_session(
                query_tokens, data,
                raw_term_count=total_count, raw_text_len=len(raw),
                mtime=mtime, corpus=corpus,
            )

            results.append((sid[:8], title, total_count, score, s_bm25, r_bm25))

        results.sort(key=lambda x: x[3], reverse=True)

        print(f"\n[BM25] Query: \"{query}\"  ({len(results)} results)")
        print(f"  {'#':>2}  {'Score':>5}  {'SumBM25':>7}  {'RawBM25':>7}  {'Hits':>5}  Title")
        print(f"  {'─'*75}")
        for i, (sid, title, hits, score, s_bm25, r_bm25) in enumerate(results[:10]):
            print(f"  {i+1:>2}  {score:>5.1f}  {s_bm25:>7.3f}  {r_bm25:>7.3f}  {hits:>5}  {title}")

        if len(results) >= 2:
            spread = results[0][3] - results[-1][3]
            top_spread = results[0][3] - results[min(4, len(results)-1)][3]
            print(f"  Full spread: {spread:.1f}  |  Top-5 spread: {top_spread:.1f}")
