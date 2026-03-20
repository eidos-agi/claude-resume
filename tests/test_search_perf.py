"""Performance tests for search_sessions optimizations.

Proves each speedup with actual timing using time.perf_counter().
"""
import json
import time
import re
import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers to exercise the two search paths without importing the full MCP
# server (which pulls in FastMCP and requires a running environment).
# We replicate the minimal logic needed to measure the path difference.
# ---------------------------------------------------------------------------


def _read_session_bytes(s: dict, chunk_size: int = 1024 * 1024):
    """Mirror of mcp_server._read_session_bytes."""
    try:
        if s["size"] < chunk_size:
            return s["file"].read_bytes().lower()
        parts = []
        with open(s["file"], "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                parts.append(chunk)
        return b"".join(parts).lower()
    except OSError:
        return None


def _extract_snippet(raw: bytes, term: bytes, context_chars: int = 80) -> str:
    """Mirror of mcp_server._extract_snippet."""
    idx = raw.find(term)
    if idx < 0:
        return ""
    start = max(0, idx - context_chars)
    end = min(len(raw), idx + len(term) + context_chars)
    snippet = raw[start:end]
    try:
        text = snippet.decode("utf-8", errors="replace")
    except Exception:
        return ""
    text = text.replace("\\n", " ").replace("\\t", " ").replace('\\"', '"')
    text = re.sub(r'["\{\}\[\]\\]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    if start > 0:
        text = "..." + text
    if end < len(raw):
        text = text + "..."
    return text


def search_raw(sessions, terms_bytes):
    """Baseline: always read raw JSONL, no cache."""
    def _check(s):
        raw = _read_session_bytes(s)
        if raw is None:
            return None
        per_term_counts = []
        for term in terms_bytes:
            c = raw.count(term)
            if c == 0:
                return None
            per_term_counts.append(c)
        total_count = sum(per_term_counts)
        min_count = min(per_term_counts)
        rarest_idx = per_term_counts.index(min_count)
        snippet = _extract_snippet(raw, terms_bytes[rarest_idx])
        return (s["session_id"], total_count, min_count, snippet)

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(_check, sessions))
    return [r for r in results if r is not None]


def search_cached(sessions, terms_bytes, cache_index, include_automated=False):
    """Optimized: cache fast path, raw fallback."""
    def _check(s):
        sid = s["session_id"]
        cached = cache_index.get(sid)

        if cached is not None and not include_automated:
            if cached.get("classification") == "automated":
                return None

        if cached is not None and cached.get("search_text"):
            raw = cached["search_text"].encode("utf-8", errors="replace")
            per_term_counts = []
            for term in terms_bytes:
                c = raw.count(term)
                if c == 0:
                    return None
                per_term_counts.append(c)
            total_count = sum(per_term_counts)
            min_count = min(per_term_counts)
            rarest_idx = per_term_counts.index(min_count)
            snippet = _extract_snippet(raw, terms_bytes[rarest_idx])
            return (sid, total_count, min_count, snippet)

        raw = _read_session_bytes(s)
        if raw is None:
            return None
        per_term_counts = []
        for term in terms_bytes:
            c = raw.count(term)
            if c == 0:
                return None
            per_term_counts.append(c)
        total_count = sum(per_term_counts)
        min_count = min(per_term_counts)
        rarest_idx = per_term_counts.index(min_count)
        snippet = _extract_snippet(raw, terms_bytes[rarest_idx])
        return (sid, total_count, min_count, snippet)

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(_check, sessions))
    return [r for r in results if r is not None]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_fake_jsonl(path: Path, target_size_bytes: int, keyword: str) -> None:
    """Write a realistic-looking JSONL file of roughly target_size_bytes."""
    line = json.dumps({
        "type": "message",
        "role": "assistant",
        "content": f"This is a session message. {keyword} appears here. " + "x" * 200,
        "timestamp": "2024-01-15T10:00:00Z",
        "uuid": "aaaa-bbbb-cccc-dddd",
    }) + "\n"
    line_bytes = line.encode()
    repeats = max(1, target_size_bytes // len(line_bytes))
    path.write_bytes(line_bytes * repeats)


def _make_fake_cache(path: Path, session_id: str, keyword: str, classification: str) -> None:
    """Write a ~2KB cache JSON file with search_text."""
    search_text = (
        f"session about {keyword} implementation. "
        f"The user asked about {keyword} patterns and best practices. "
        + ("filler content about the session work. " * 20)
    ).lower()
    data = {
        "cache_key": "sha256:abc123",
        "classification": classification,
        "search_text": search_text,
        "summary": {
            "title": f"Session on {keyword}",
            "goal": f"Implement {keyword}",
            "what_was_done": f"Discussed {keyword}",
            "state": "done",
            "files": [],
        },
        "stats": {"messages": 10, "size_kb": 1024},
    }
    path.write_text(json.dumps(data))


# ---------------------------------------------------------------------------
# Test 1: Cache fast path is significantly faster than raw reads
# ---------------------------------------------------------------------------


def test_cache_fast_path_vs_raw(tmp_path):
    """Cache path should be >5x faster than reading raw 1MB JSONL files."""
    n = 100
    keyword = "authentication"
    terms_bytes = [keyword.encode("utf-8")]

    sessions_dir = tmp_path / "sessions"
    cache_dir = tmp_path / "cache"
    sessions_dir.mkdir()
    cache_dir.mkdir()

    sessions = []
    for i in range(n):
        sid = f"aaaaaaaa-bbbb-cccc-dddd-{i:012d}"
        jsonl_file = sessions_dir / f"{sid}.jsonl"
        _make_fake_jsonl(jsonl_file, 1_000_000, keyword)  # 1MB each
        stat = jsonl_file.stat()
        sessions.append({
            "file": jsonl_file,
            "session_id": sid,
            "project_dir": str(tmp_path),
            "mtime": stat.st_mtime,
            "size": stat.st_size,
        })

        cache_file = cache_dir / f"{sid}.json"
        _make_fake_cache(cache_file, sid, keyword, "interactive")

    # Build cache index
    cache_index = {}
    for cache_file in cache_dir.glob("*.json"):
        sid = cache_file.stem
        cache_index[sid] = json.loads(cache_file.read_bytes())

    # Warm filesystem cache with one throwaway read
    _ = sessions[0]["file"].read_bytes()

    # Time raw path
    t0 = time.perf_counter()
    raw_results = search_raw(sessions, terms_bytes)
    raw_elapsed = time.perf_counter() - t0

    # Time cached path
    t0 = time.perf_counter()
    cached_results = search_cached(sessions, terms_bytes, cache_index, include_automated=True)
    cached_elapsed = time.perf_counter() - t0

    speedup = raw_elapsed / max(cached_elapsed, 1e-9)
    print(f"\n[test_cache_fast_path_vs_raw]")
    print(f"  Raw path:    {raw_elapsed:.3f}s  ({len(raw_results)} hits)")
    print(f"  Cached path: {cached_elapsed:.3f}s  ({len(cached_results)} hits)")
    print(f"  Speedup:     {speedup:.1f}x")

    # Results must be identical (same session IDs)
    raw_ids = {r[0] for r in raw_results}
    cached_ids = {r[0] for r in cached_results}
    assert raw_ids == cached_ids, f"Result mismatch: raw={len(raw_ids)} cached={len(cached_ids)}"

    assert speedup > 5, f"Expected >5x speedup, got {speedup:.1f}x"


# ---------------------------------------------------------------------------
# Test 2: ML pre-filter reduces corpus
# ---------------------------------------------------------------------------


def test_ml_prefilter_reduces_corpus(tmp_path):
    """Automated sessions should be skipped by default, interactive always searched."""
    n_automated = 50
    n_interactive = 10
    keyword = "deployment"
    terms_bytes = [keyword.encode("utf-8")]

    sessions_dir = tmp_path / "sessions"
    cache_dir = tmp_path / "cache"
    sessions_dir.mkdir()
    cache_dir.mkdir()

    sessions = []

    def _make_session(i, classification):
        sid = f"bbbbbbbb-{classification[:4]}-cccc-dddd-{i:012d}"
        jsonl_file = sessions_dir / f"{sid}.jsonl"
        _make_fake_jsonl(jsonl_file, 50_000, keyword)
        stat = jsonl_file.stat()
        s = {
            "file": jsonl_file,
            "session_id": sid,
            "project_dir": str(tmp_path),
            "mtime": stat.st_mtime,
            "size": stat.st_size,
        }
        cache_file = cache_dir / f"{sid}.json"
        _make_fake_cache(cache_file, sid, keyword, classification)
        return s

    for i in range(n_automated):
        sessions.append(_make_session(i, "automated"))
    for i in range(n_interactive):
        sessions.append(_make_session(i + n_automated, "interactive"))

    cache_index = {}
    for cache_file in cache_dir.glob("*.json"):
        cache_index[cache_file.stem] = json.loads(cache_file.read_bytes())

    # Default: exclude automated
    results_no_auto = search_cached(sessions, terms_bytes, cache_index, include_automated=False)
    # Include automated
    results_with_auto = search_cached(sessions, terms_bytes, cache_index, include_automated=True)

    auto_ids = {s["session_id"] for s in sessions if "automated" in s["session_id"]}
    interactive_ids = {s["session_id"] for s in sessions if "interactive" in s["session_id"] or "inte" in s["session_id"]}

    found_without = {r[0] for r in results_no_auto}
    found_with = {r[0] for r in results_with_auto}

    # All automated sessions excluded when include_automated=False
    assert not (found_without & auto_ids), "Automated sessions leaked into default search"
    # All interactive sessions found in both modes
    assert interactive_ids.issubset(found_without), "Interactive sessions missing from default search"
    assert interactive_ids.issubset(found_with), "Interactive sessions missing from include_automated search"
    # All sessions found when include_automated=True
    assert len(found_with) == n_automated + n_interactive

    reduction_pct = (1 - len(results_no_auto) / len(results_with_auto)) * 100
    print(f"\n[test_ml_prefilter_reduces_corpus]")
    print(f"  Total sessions: {n_automated + n_interactive}")
    print(f"  With include_automated=False: {len(results_no_auto)} searched")
    print(f"  With include_automated=True:  {len(results_with_auto)} searched")
    print(f"  Corpus reduction: {reduction_pct:.0f}%")


# ---------------------------------------------------------------------------
# Test 3: Cached search_text produces cleaner snippets
# ---------------------------------------------------------------------------


def test_snippet_quality_cached_vs_raw(tmp_path):
    """Cached search_text snippets should have no JSON escape sequences."""
    keyword = "kubernetes"
    terms_bytes = [keyword.encode("utf-8")]

    sessions_dir = tmp_path / "sessions"
    cache_dir = tmp_path / "cache"
    sessions_dir.mkdir()
    cache_dir.mkdir()

    sid = "cccccccc-dddd-eeee-ffff-000000000001"
    jsonl_file = sessions_dir / f"{sid}.jsonl"
    _make_fake_jsonl(jsonl_file, 500_000, keyword)
    stat = jsonl_file.stat()
    s = {
        "file": jsonl_file,
        "session_id": sid,
        "project_dir": str(tmp_path),
        "mtime": stat.st_mtime,
        "size": stat.st_size,
    }

    cache_file = cache_dir / f"{sid}.json"
    _make_fake_cache(cache_file, sid, keyword, "interactive")

    cache_index = {sid: json.loads(cache_file.read_bytes())}

    # Get raw snippet
    raw_bytes = _read_session_bytes(s)
    raw_snippet = _extract_snippet(raw_bytes, terms_bytes[0])

    # Get cached snippet
    cached_results = search_cached([s], terms_bytes, cache_index, include_automated=True)
    assert cached_results, "Expected at least one cached result"
    cached_snippet = cached_results[0][3]

    print(f"\n[test_snippet_quality_cached_vs_raw]")
    print(f"  Raw snippet:    {repr(raw_snippet[:120])}")
    print(f"  Cached snippet: {repr(cached_snippet[:120])}")

    # Cached snippet should have no JSON escape sequences
    # (raw snippet from JSONL may still contain them despite _extract_snippet cleanup,
    #  because the source text itself is JSON-encoded)
    json_escapes = ["\\n", "\\t", '\\"', "\\\\"]
    cached_has_escapes = any(e in cached_snippet for e in json_escapes)
    assert not cached_has_escapes, f"Cached snippet contains JSON escapes: {repr(cached_snippet)}"

    # Cached snippet should contain the keyword
    assert keyword in cached_snippet.lower(), f"Keyword not in cached snippet: {repr(cached_snippet)}"


# ---------------------------------------------------------------------------
# Test 4: Real data benchmark (skip if no cache files)
# ---------------------------------------------------------------------------


def test_real_data_benchmark():
    """Benchmark against actual ~/.claude/resume-summaries/ if available."""
    cache_dir = Path.home() / ".claude" / "resume-summaries"
    if not cache_dir.exists():
        pytest.skip("No real cache directory found")

    cache_files = list(cache_dir.glob("*.json"))
    if len(cache_files) < 10:
        pytest.skip(f"Too few cache files ({len(cache_files)}) for meaningful benchmark")

    # Common search term likely to appear in many sessions
    search_term = "python"
    terms_bytes = [search_term.encode("utf-8")]

    # Load real cache
    t_load_start = time.perf_counter()
    cache_index = {}
    for cache_file in cache_files:
        sid = cache_file.stem
        try:
            cache_index[sid] = json.loads(cache_file.read_bytes())
        except Exception:
            pass
    t_load = time.perf_counter() - t_load_start

    # Build fake session list from cache (we don't need real JSONL for timing the cache path)
    # We use the cache to synthesize session dicts with plausible sizes
    sessions = []
    for sid, data in cache_index.items():
        size_kb = data.get("stats", {}).get("size_kb", 500)
        sessions.append({
            "file": cache_dir / f"{sid}.jsonl",  # may not exist — that's fine for cache path
            "session_id": sid,
            "project_dir": "~",
            "mtime": time.time() - 86400,
            "size": size_kb * 1024,
        })

    # Time cached search
    t0 = time.perf_counter()
    results = search_cached(sessions, terms_bytes, cache_index, include_automated=False)
    cached_elapsed = time.perf_counter() - t0

    # Count how many had cache hits vs would need raw fallback
    cache_hits = sum(1 for s in sessions if cache_index.get(s["session_id"], {}).get("search_text"))
    raw_needed = len(sessions) - cache_hits

    # Estimate baseline: assume 2MB avg per session, 500MB/s disk bandwidth
    avg_session_bytes = 2 * 1024 * 1024
    disk_bandwidth = 500 * 1024 * 1024
    estimated_raw_time = (len(sessions) * avg_session_bytes) / disk_bandwidth
    estimated_speedup = estimated_raw_time / max(cached_elapsed, 1e-9)

    print(f"\n[test_real_data_benchmark]")
    print(f"  Cache files loaded: {len(cache_index)} in {t_load:.3f}s")
    print(f"  Sessions scanned:   {len(sessions)}")
    print(f"  Cache hits:         {cache_hits} ({100*cache_hits//max(len(sessions),1)}%)")
    print(f"  Raw reads needed:   {raw_needed}")
    print(f"  Search wall time:   {cached_elapsed:.3f}s")
    print(f"  Results found:      {len(results)}")
    print(f"  Est. speedup vs baseline (2MB/session, 500MB/s disk): {estimated_speedup:.0f}x")

    # Basic sanity: should complete in reasonable time
    assert cached_elapsed < 30, f"Search took too long: {cached_elapsed:.1f}s"
