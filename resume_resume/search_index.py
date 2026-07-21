"""SQLite-backed cold search index for resume-resume.

The MCP hot path should not parse tens of thousands of summary files just to
answer a query. This module keeps older, stable session summaries in FTS5 and
lets callers combine it with a tiny live scan of recently touched sessions.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

DATA_DIR = Path.home() / ".claude-resume-duet"
DB_PATH = DATA_DIR / "resume-resume-search.db"
RESUME_CACHE_DIR = Path.home() / ".claude" / "resume-summaries"

HOT_WINDOW_SECONDS = 30 * 60
_SESSION_INDEX_CACHE: dict[str, dict] | None = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    summary_path TEXT NOT NULL,
    mtime REAL NOT NULL,
    indexed_at REAL NOT NULL,
    project_dir TEXT,
    classification TEXT,
    score REAL,
    title TEXT,
    state TEXT,
    summary_json TEXT
);

CREATE VIRTUAL TABLE IF NOT EXISTS sessions_fts USING fts5(
    session_id UNINDEXED,
    project_dir UNINDEXED,
    title,
    body
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    if _meta_get(conn, "fts_schema_version") != "3":
        conn.execute("DROP TABLE IF EXISTS sessions_fts")
        conn.execute(
            """CREATE VIRTUAL TABLE sessions_fts USING fts5(
               session_id UNINDEXED,
               project_dir UNINDEXED,
               title,
               body
            )"""
        )
        conn.execute("DELETE FROM sessions")
        _meta_set(conn, "fts_schema_version", "3")
        _meta_set(conn, "cursor_name", "")
        conn.commit()
    return conn


def _meta_get(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return str(row["value"]) if row else default


def _meta_set(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
        (key, value),
    )


def _summary_text(summary: dict[str, Any], data: dict[str, Any]) -> tuple[str, str]:
    title_lines = str(summary.get("title") or "").splitlines()
    title = title_lines[0].strip() if title_lines else ""
    parts = [
        title,
        str(summary.get("goal") or summary.get("objective") or ""),
        str(summary.get("what_was_done") or summary.get("progress") or ""),
        str(summary.get("state") or ""),
        " ".join(str(x) for x in (summary.get("files") or [])),
        str(data.get("search_text") or ""),
    ]
    return title, "\n".join(p for p in parts if p)


def _parse_summary_file(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text())
    except Exception:
        return None

    summary = data.get("summary") or {}
    if not isinstance(summary, dict):
        return None

    title, body = _summary_text(summary, data)
    if not title and not body.strip():
        return None

    meta = _session_meta(path.stem)
    project_dir = (
        summary.get("project_dir")
        or data.get("project_dir")
        or meta.get("project_dir")
        or ""
    )
    # TASK-0029: never leave project_dir empty when SessionIndex / discovery
    # can supply it. Also try a cheap filesystem resolve for Claude/Grok.
    if not project_dir:
        project_dir = _resolve_project_dir(path.stem) or ""

    return {
        "session_id": path.stem,
        "summary_path": str(path),
        "mtime": float(meta.get("mtime") or path.stat().st_mtime),
        "project_dir": project_dir,
        "classification": data.get("classification") or "",
        "score": float(data.get("resumability_score") or 0.0),
        "title": title,
        "state": summary.get("state") or "",
        "summary_json": json.dumps(summary),
        "body": body,
    }


def _resolve_project_dir(session_id: str) -> str:
    """Best-effort project_dir for a session id when summary meta is empty."""
    if not session_id:
        return ""
    try:
        from claude_session_commons.paths import decode_project_path
        from claude_session_commons.discovery import PROJECTS_DIR
    except Exception:
        try:
            from claude_session_commons import decode_project_path
            from pathlib import Path as _P

            PROJECTS_DIR = _P.home() / ".claude" / "projects"
        except Exception:
            return ""

    try:
        if not session_id.startswith("rollout-"):
            matches = list(PROJECTS_DIR.glob(f"*/{session_id}.jsonl"))
            if matches:
                return decode_project_path(matches[0].parent.name)
    except Exception:
        pass

    try:
        from resume_resume.session_utils import find_grok_session_file

        grok = find_grok_session_file(session_id)
        if grok is not None:
            return grok[1]
    except Exception:
        pass
    return ""


def _session_meta(session_id: str) -> dict[str, Any]:
    global _SESSION_INDEX_CACHE
    if _SESSION_INDEX_CACHE is None:
        try:
            from claude_session_commons.session_index import SessionIndex

            _SESSION_INDEX_CACHE = SessionIndex.get_default().get_all()
        except Exception:
            _SESSION_INDEX_CACHE = {}
    return _SESSION_INDEX_CACHE.get(session_id, {})


def refresh_budget(
    *,
    max_files: int = 200,
    max_seconds: float = 0.25,
    hot_window_seconds: int = HOT_WINDOW_SECONDS,
) -> dict[str, Any]:
    """Index a small batch of cold summaries without monopolizing the machine.

    The cursor is deliberately simple: continue after the last processed file
    name in the directory's natural order. If the directory order changes, the
    next pass may revisit already-indexed rows, but unchanged rows are skipped.
    """
    if not RESUME_CACHE_DIR.exists():
        return {"indexed": 0, "checked": 0, "done": True}

    conn = _connect()
    cursor = _meta_get(conn, "cursor_name")
    found_cursor = not cursor
    start = time.monotonic()
    cold_cutoff = time.time() - hot_window_seconds
    checked = 0
    indexed = 0
    last_name = ""
    done = True

    try:
        with os.scandir(RESUME_CACHE_DIR) as it:
            for entry in it:
                if not entry.name.endswith(".json") or not entry.is_file():
                    continue
                if not found_cursor:
                    if entry.name == cursor:
                        found_cursor = True
                    continue

                if checked >= max_files or (time.monotonic() - start) >= max_seconds:
                    done = False
                    break

                checked += 1
                last_name = entry.name
                path = Path(entry.path)
                try:
                    stat = path.stat()
                except OSError:
                    continue
                if stat.st_mtime >= cold_cutoff:
                    continue

                row = conn.execute(
                    "SELECT mtime FROM sessions WHERE session_id = ?",
                    (path.stem,),
                ).fetchone()
                if row and float(row["mtime"]) == stat.st_mtime:
                    continue

                parsed = _parse_summary_file(path)
                if not parsed:
                    continue

                conn.execute(
                    """INSERT OR REPLACE INTO sessions
                       (session_id, summary_path, mtime, indexed_at, project_dir,
                        classification, score, title, state, summary_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        parsed["session_id"],
                        parsed["summary_path"],
                        parsed["mtime"],
                        time.time(),
                        parsed["project_dir"],
                        parsed["classification"],
                        parsed["score"],
                        parsed["title"],
                        parsed["state"],
                        parsed["summary_json"],
                    ),
                )
                conn.execute(
                    "DELETE FROM sessions_fts WHERE session_id = ?",
                    (parsed["session_id"],),
                )
                conn.execute(
                    """INSERT INTO sessions_fts
                       (session_id, project_dir, title, body)
                       VALUES (?, ?, ?, ?)""",
                    (
                        parsed["session_id"],
                        parsed["project_dir"],
                        parsed["title"],
                        parsed["body"],
                    ),
                )
                indexed += 1
    finally:
        _meta_set(conn, "cursor_name", "" if done else last_name or cursor)
        _meta_set(conn, "last_refresh_at", str(time.time()))
        conn.commit()
        conn.close()

    return {"indexed": indexed, "checked": checked, "done": done}


def status() -> dict[str, Any]:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT count(*) AS c, max(indexed_at) AS latest FROM sessions"
        ).fetchone()
        return {
            "path": str(DB_PATH),
            "sessions": int(row["c"] or 0),
            "latest_indexed_at": float(row["latest"] or 0.0),
            "cursor_name": _meta_get(conn, "cursor_name"),
        }
    finally:
        conn.close()


def _fts_query(query: str) -> str:
    import re

    phrases = [p.strip().replace('"', "") for p in re.findall(r'"([^"]+)"', query)]
    remaining = re.sub(r'"[^"]*"', "", query)
    words = [t.replace('"', "") for t in remaining.lower().split() if t.strip()]
    tokens = [t for t in [*phrases, *words] if t]
    # Join with OR so a query is tolerant of missing words: a session need not
    # contain every term to match. bm25() ranking (see search()) naturally floats
    # sessions matching more query terms to the top.
    return " OR ".join(f'"{t}"' for t in tokens)


def search(
    query: str,
    *,
    limit: int,
    include_automated: bool = False,
    cutoff_after: float = 0.0,
    cutoff_before: float = 0.0,
    project: str = "",
) -> list[dict[str, Any]]:
    fts = _fts_query(query)
    if not fts:
        return []

    conn = _connect()
    try:
        where = ["sessions_fts MATCH ?"]
        params: list[Any] = [fts]
        if not include_automated:
            where.append(
                "(s.classification IS NULL OR s.classification != 'automated')"
            )
        if cutoff_after:
            where.append("s.mtime >= ?")
            params.append(cutoff_after)
        if cutoff_before:
            where.append("s.mtime < ?")
            params.append(cutoff_before)
        if project:
            where.append("lower(s.project_dir) LIKE ?")
            params.append(f"%{project.lower()}%")

        params.append(limit)
        rows = conn.execute(
            f"""SELECT s.session_id, s.project_dir, s.mtime, s.score, s.title,
                       s.state, s.classification, bm25(sessions_fts) AS rank
                FROM sessions_fts
                JOIN sessions s ON s.session_id = sessions_fts.session_id
                WHERE {" AND ".join(where)}
                ORDER BY rank ASC, s.mtime DESC
                LIMIT ?""",
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def count_matches(
    query: str,
    *,
    include_automated: bool = False,
    cutoff_after: float = 0.0,
    cutoff_before: float = 0.0,
    project: str = "",
    excluded_title_prefixes: tuple[str, ...] = (),
) -> int:
    fts = _fts_query(query)
    if not fts:
        return 0

    conn = _connect()
    try:
        where = ["sessions_fts MATCH ?"]
        params: list[Any] = [fts]
        if not include_automated:
            where.append(
                "(s.classification IS NULL OR s.classification != 'automated')"
            )
        if cutoff_after:
            where.append("s.mtime >= ?")
            params.append(cutoff_after)
        if cutoff_before:
            where.append("s.mtime < ?")
            params.append(cutoff_before)
        if project:
            where.append("lower(s.project_dir) LIKE ?")
            params.append(f"%{project.lower()}%")
        for prefix in excluded_title_prefixes:
            where.append("lower(coalesce(s.title, '')) NOT LIKE ?")
            params.append(f"{prefix.lower()}%")

        row = conn.execute(
            f"""SELECT count(*) AS c
                FROM sessions_fts
                JOIN sessions s ON s.session_id = sessions_fts.session_id
                WHERE {" AND ".join(where)}""",
            params,
        ).fetchone()
        return int(row["c"] or 0)
    finally:
        conn.close()


def recent_candidates(
    *,
    limit: int = 100,
    cutoff_after: float = 0.0,
    include_automated: bool = False,
) -> list[dict[str, Any]]:
    conn = _connect()
    try:
        where = ["1=1"]
        params: list[Any] = []
        if cutoff_after:
            where.append("mtime >= ?")
            params.append(cutoff_after)
        if not include_automated:
            where.append("(classification IS NULL OR classification != 'automated')")
        params.append(limit)
        rows = conn.execute(
            f"""SELECT session_id, summary_path, mtime, project_dir, classification,
                       score, title, state, summary_json
                FROM sessions
                WHERE {" AND ".join(where)}
                ORDER BY mtime DESC
                LIMIT ?""",
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
