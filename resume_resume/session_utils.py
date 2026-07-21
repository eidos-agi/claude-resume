"""Shared session utility functions.

Small helpers used by both mcp_server.py and self_tools.py.
Extracted to keep mcp_server.py under 2000 lines.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

# Default Grok Build session root. Overridable in tests via session_tool(..., grok_root=).
GROK_SESSIONS_DIR = Path.home() / ".grok" / "sessions"

# Cache: session_id → bool (is under grok root). Invalidated when root mtime changes.
_GROK_ID_CACHE: dict[str, bool] = {}
_GROK_ROOT_MTIME: float | None = None


def _grok_root_mtime(root: Path) -> float | None:
    try:
        return root.stat().st_mtime if root.is_dir() else None
    except OSError:
        return None


def is_grok_session_id(session_id: str, *, grok_root: Path | None = None) -> bool:
    """True if session_id is a directory under ~/.grok/sessions/<project>/<id>/.

    Path existence is the source of truth — Grok IDs look like UUIDs and cannot
    be distinguished from Claude UUIDs by format alone (see MS-0002 / TASK-0025).
    """
    if not session_id or session_id.startswith("rollout-"):
        return False
    # Guard against path traversal in globs
    if "/" in session_id or "\\" in session_id or ".." in session_id:
        return False

    root = grok_root if grok_root is not None else GROK_SESSIONS_DIR
    global _GROK_ID_CACHE, _GROK_ROOT_MTIME
    mtime = _grok_root_mtime(root)
    if grok_root is None:
        if mtime != _GROK_ROOT_MTIME:
            _GROK_ID_CACHE = {}
            _GROK_ROOT_MTIME = mtime
        cached = _GROK_ID_CACHE.get(session_id)
        if cached is not None:
            return cached

    found = False
    try:
        if root.is_dir():
            # One level: <encoded-cwd>/<session_id>/
            for match in root.glob(f"*/{session_id}"):
                if match.is_dir():
                    found = True
                    break
    except OSError:
        found = False

    if grok_root is None:
        _GROK_ID_CACHE[session_id] = found
    return found


def decode_grok_project_dir(encoded: str) -> str:
    """Decode a Grok sessions parent dir name into a filesystem cwd.

    Grok encodes cwd as URL-quoted path segments (e.g. ``%2FUsers%2Fme%2Fproj``).
    """
    from urllib.parse import unquote

    path = unquote(encoded.replace("%2F", "/").replace("%2f", "/"))
    if path and not path.startswith("/"):
        path = "/" + path
    return path or encoded


def find_grok_session_file(
    session_id: str,
    *,
    grok_root: Path | None = None,
) -> tuple[Path, str] | None:
    """Locate ``chat_history.jsonl`` (or fallback) for a Grok session id.

    Returns ``(file, project_dir)`` or None. project_dir is the decoded cwd.
    """
    if not session_id or session_id.startswith("rollout-"):
        return None
    if "/" in session_id or "\\" in session_id or ".." in session_id:
        return None

    root = grok_root if grok_root is not None else GROK_SESSIONS_DIR
    try:
        if not root.is_dir():
            return None
        for match in root.glob(f"*/{session_id}"):
            if not match.is_dir():
                continue
            for name in ("chat_history.jsonl", "events.jsonl", "updates.jsonl"):
                candidate = match / name
                if candidate.is_file():
                    project_dir = decode_grok_project_dir(match.parent.name)
                    return candidate, project_dir
    except OSError:
        return None
    return None


def is_claude_session_id(session_id: str, *, projects_dir: Path | None = None) -> bool:
    """True if ``~/.claude/projects/*/<session_id>.jsonl`` exists."""
    if not session_id or session_id.startswith("rollout-"):
        return False
    if "/" in session_id or "\\" in session_id or ".." in session_id:
        return False
    root = projects_dir if projects_dir is not None else Path.home() / ".claude" / "projects"
    try:
        if not root.is_dir():
            return False
        for match in root.glob(f"*/{session_id}.jsonl"):
            if match.is_file():
                return True
    except OSError:
        return False
    return False


def session_tool(
    session_id: str,
    *,
    grok_root: Path | None = None,
    projects_dir: Path | None = None,
) -> str:
    """Which CLI produced a session: ``"codex"``, ``"grok"``, or ``"claude"``.

    Rules (TASK-0025 / MS-0002):
      - ``rollout-*`` → codex
      - Claude projects path exists → claude (wins over grok if both — pathological)
      - directory under ``~/.grok/sessions/*/<id>/`` → grok
      - else → claude

    Dual-path collision is not expected in production (Claude and Grok use
    separate trees and do not share ids). Claude wins if it ever happens so
    we do not mislabel a real Claude UUID.

    Lives in resume-resume (not claude-session-commons) so this PR does not
    change the binary codex|claude helper still used by other packages.
    """
    if not session_id:
        return "claude"
    if session_id.startswith("rollout-"):
        return "codex"
    if is_claude_session_id(session_id, projects_dir=projects_dir):
        return "claude"
    if is_grok_session_id(session_id, grok_root=grok_root):
        return "grok"
    return "claude"


def resume_command(
    session_id: str,
    *,
    fork: bool = False,
    skip_permissions: bool = False,
    grok_root: Path | None = None,
    projects_dir: Path | None = None,
) -> str:
    """Build the CLI command to resume (or fork) a session, by source.

    Claude Code → ``claude --resume <id>`` (``--fork-session`` to fork).
    Codex CLI   → ``codex resume <uuid>`` (``codex fork <uuid>`` to fork),
    Grok Build  → ``grok --resume <id>``,
    where the UUID is extracted from the rollout filename stem.

    ``skip_permissions`` only applies to Claude Code; Codex has no equivalent
    flag and ignores it.
    """
    from claude_session_commons.codex import (
        codex_session_uuid,
        is_codex_session_id,
    )

    host = session_tool(
        session_id, grok_root=grok_root, projects_dir=projects_dir
    )
    if host == "codex" or is_codex_session_id(session_id):
        verb = "fork" if fork else "resume"
        return f"codex {verb} {codex_session_uuid(session_id)}"

    if host == "grok":
        return f"grok --resume {session_id}"

    cmd = f"claude --resume {session_id}"
    if fork:
        cmd += " --fork-session"
    if skip_permissions:
        cmd += " --dangerously-skip-permissions"
    return cmd


def filter_automated(sessions: list[dict], cache_index: dict) -> list[dict]:
    """Remove sessions classified as 'automated' by the ML classifier.

    Shared helper — used by search_sessions, recent_sessions, what_changed,
    my_week, healthy_sessions, and suggest_next. Extracted to avoid 6
    copies of the same filter pattern.
    """
    return [
        s
        for s in sessions
        if cache_index.get(s.get("session_id", ""), {}).get("classification")
        != "automated"
    ]


def session_duration_hours(f: Path) -> float:
    """Estimate session duration. Prefers file birthtime (measures current
    file lifespan, conservative). Falls back to JSONL first→last timestamps
    when birthtime is unavailable. Capped at 24h — sessions left open for
    days shouldn't count full idle time as work.
    """
    try:
        stat = f.stat()
        try:
            birth = stat.st_birthtime
            delta = stat.st_mtime - birth
            if delta > 60:
                return min(delta / 3600, 24.0)
        except AttributeError:
            pass

        size = stat.st_size
        if size < 100:
            return 0.0
        first_ts = None
        with open(f, "rb") as fh:
            for _ in range(20):
                line = fh.readline()
                if not line:
                    break
                try:
                    entry = json.loads(line.decode("utf-8", errors="replace"))
                    ts = entry.get("timestamp")
                    if ts:
                        first_ts = ts
                        break
                except (json.JSONDecodeError, ValueError):
                    pass
        last_ts = None
        if first_ts:
            with open(f, "rb") as fh:
                fh.seek(max(0, size - 2048))
                tail = fh.read().decode("utf-8", errors="replace")
                for line in reversed(tail.splitlines()):
                    if not line.strip():
                        continue
                    try:
                        entry = json.loads(line.strip())
                        ts = entry.get("timestamp")
                        if ts:
                            last_ts = ts
                            break
                    except (json.JSONDecodeError, ValueError):
                        continue
        if first_ts and last_ts:
            t0 = datetime.fromisoformat(str(first_ts).replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(str(last_ts).replace("Z", "+00:00"))
            delta = (t1 - t0).total_seconds()
            if delta > 60:
                return min(delta / 3600, 24.0)
    except (OSError, ValueError, TypeError):
        pass
    return 0.0
