"""MS-0002 TASK-0033: cold FTS always runs; hot does not starve cold slots."""

from __future__ import annotations

from resume_resume import mcp_server as ms


def test_search_always_queries_cold_even_when_hot_fills_limit(tmp_path, monkeypatch):
    """When hot returns >= limit matches, cold must still be queried."""
    cold_calls = []

    def fake_cold(query, **kwargs):
        cold_calls.append({"query": query, **kwargs})
        return [
            {
                "session_id": "727d811c-41f7-42f7-b517-ba4c525baf4e",
                "project_dir": "/Users/dshanklinbv/repos-aic/northstar",
                "mtime": 1_700_000_000.0,
                "score": 50.0,
                "title": "Chapter 4 case study held pending trade blotter evidence",
                "rank": -19.7,
                "state": "HELD until blotter",
            }
        ]

    # Build fake hot sessions that all "match" (need real file paths for health)
    hot_sessions = []
    for i in range(15):
        sid = (
            f"019f82e1-d2b1-7db1-a82a-77f1f32fd9e{i:01x}"
            if i < 10
            else f"aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeee{i:02d}"
        )
        f = tmp_path / f"{sid}.jsonl"
        f.write_text("northstar loop mission-north-star blotter\n")
        hot_sessions.append(
            {
                "session_id": sid,
                "project_dir": "/tmp/hot",
                "mtime": 1_800_000_000.0 + i,
                "file": f,
                "size": f.stat().st_size,
            }
        )

    monkeypatch.setattr(ms, "_hot_sessions", lambda: hot_sessions[:12])
    monkeypatch.setattr(ms, "_fresh_sessions", lambda cutoff_after=0.0: [])
    monkeypatch.setattr(ms, "search_cold_index", fake_cold)
    monkeypatch.setattr(
        ms,
        "_read_session_bytes",
        lambda s: b"northstar loop mission-north-star blotter",
    )
    monkeypatch.setattr(ms, "session_tool", lambda sid: "claude")
    monkeypatch.setattr(ms, "search_index_status", lambda: {"sessions": 1})

    # silence progress UI
    class _P:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def update(self, *a, **k):
            pass

    monkeypatch.setattr(ms, "progress", lambda *a, **k: _P())

    out = ms.search_sessions.fn("northstar", limit=5)
    assert cold_calls, "cold index must always be queried"
    assert cold_calls[0]["limit"] == 5, (
        "cold queried for full limit, not remaining slots"
    )
    assert out["cold_matches"] >= 1
    ids = [r["id"] for r in out["items"]]
    # Anchor 727d811c (2026-07-21 northstar failure): must SURFACE in items even when
    # hot has >= limit matches with higher recency scores (fair merge reserves cold slots).
    assert "727d811c-41f7-42f7-b517-ba4c525baf4e" in ids, ids
    cold_in_items = [r for r in out["items"] if r.get("source") == "cold-index"]
    assert cold_in_items, (
        "at least one cold-index row must appear when cold has matches"
    )


def test_search_tool_filter_claude(monkeypatch):
    """TASK-0030: tool=claude excludes non-claude hosts."""
    monkeypatch.setattr(ms, "_hot_sessions", lambda: [])
    monkeypatch.setattr(ms, "_fresh_sessions", lambda cutoff_after=0.0: [])

    def fake_cold(query, **kwargs):
        return [
            {
                "session_id": "rollout-2026-06-12T08-36-57-019ebc0c-9f4f-7362-9d26-fb071dfeecbe",
                "project_dir": "/tmp",
                "mtime": 1_700_000_000.0,
                "score": 10.0,
                "title": "codex hit",
                "rank": -5.0,
                "state": "codex",
            },
            {
                "session_id": "ddf7fc98-6c93-40c8-9444-503d8a716dbf",
                "project_dir": "/tmp",
                "mtime": 1_700_000_001.0,
                "score": 10.0,
                "title": "claude hit",
                "rank": -5.0,
                "state": "claude",
            },
        ]

    monkeypatch.setattr(ms, "search_cold_index", fake_cold)
    monkeypatch.setattr(ms, "search_index_status", lambda: {})

    class _P:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def update(self, *a, **k):
            pass

    monkeypatch.setattr(ms, "progress", lambda *a, **k: _P())

    # Force tool labels without filesystem
    def fake_tool(sid):
        if sid.startswith("rollout-"):
            return "codex"
        return "claude"

    monkeypatch.setattr(ms, "session_tool", fake_tool)

    out = ms.search_sessions.fn("hit", limit=10, tool="claude")
    assert out["count"] == 1
    assert out["items"][0]["id"] == "ddf7fc98-6c93-40c8-9444-503d8a716dbf"
    assert out["items"][0]["tool"] == "claude"
