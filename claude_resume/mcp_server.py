"""MCP server exposing claude-resume session search and reading tools.

Design: minimize tokens returned. Claude can construct 'claude --resume {id}'
itself — don't waste tokens repeating it. Return the minimum needed to answer
the user's question in one tool call when possible.
"""

import json
import math
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .sessions import (
    SessionCache,
    find_all_sessions,
    find_recent_sessions,
    parse_session,
    get_git_context,
    shorten_path,
    PROJECTS_DIR,
)
from claude_session_commons import decode_project_path
from .summarize import summarize_quick

mcp = FastMCP("claude-resume")

_cache = SessionCache()

_TRUNC = 300  # max chars per message/field
_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _find_session(session_id: str) -> dict | None:
    """Find a session by targeted glob — O(1) dirs, not O(N) sessions."""
    # Validate UUID format to prevent glob injection (* ? [] etc)
    if not _UUID_RE.fullmatch(session_id):
        return None
    matches = list(PROJECTS_DIR.glob(f"*/{session_id}.jsonl"))
    if not matches:
        return None
    f = matches[0]
    stat = f.stat()
    return {
        "file": f,
        "session_id": session_id,
        "project_dir": decode_project_path(f.parent.name),
        "mtime": stat.st_mtime,
        "size": stat.st_size,
    }


def _trunc(text: str, limit: int = _TRUNC) -> str:
    return text if len(text) <= limit else text[:limit] + "..."


def _daemon_alive() -> bool:
    pid_file = Path.home() / ".claude" / "session-daemon.pid"
    try:
        if not pid_file.exists():
            return False
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)
        return True
    except (ValueError, ProcessLookupError, PermissionError, OSError):
        return False


def _queue_to_daemon(session_id: str, session_file: str, project_dir: str) -> None:
    task_dir = Path.home() / ".claude" / "daemon-tasks"
    task_dir.mkdir(parents=True, exist_ok=True)
    priority = int(time.time() * 1000)
    task = {
        "kind": "summarize",
        "session_id": session_id,
        "file": session_file,
        "project_dir": project_dir,
        "quick_summary": None,
    }
    (task_dir / f"{priority}-summarize-{session_id[:8]}.json").write_text(json.dumps(task))


def _get_title(session_id: str, session_file: Path) -> str:
    """Get cached title, falling back to stale cache if current key doesn't match."""
    ck = _cache.cache_key(session_file)
    cached = _cache.get(session_id, ck, "summary")
    if cached:
        return cached.get("title", "")
    # Stale cache — read directly, title is still useful
    data = _cache._read(session_id)
    summary = data.get("summary")
    return summary.get("title", "") if isinstance(summary, dict) else ""


def _session_row(s: dict, extra: dict | None = None) -> dict:
    """Standard compact session row. Omits resume_cmd (caller knows the pattern)."""
    row = {
        "id": s["session_id"],
        "project": shorten_path(s["project_dir"]),
        "date": datetime.fromtimestamp(s["mtime"]).strftime("%Y-%m-%d %H:%M"),
        "title": _get_title(s["session_id"], s["file"]),
    }
    if extra:
        row.update(extra)
    return row


@mcp.tool()
def search_sessions(query: str, limit: int = 10) -> list[dict]:
    """Search all Claude Code sessions for a keyword (~3s for 3000 sessions).

    Returns matches ranked by relevance (50% time decay with 7-day half-life +
    50% normalized √match-count). Use read_session() to drill into a specific
    result. Resume any session with: claude --resume <id>
    """
    query = query.strip()
    if not query:
        return []
    limit = max(1, min(limit, 25))
    term_bytes = query.lower().encode("utf-8", errors="replace")
    all_sessions = find_all_sessions()

    _CHUNK = 1024 * 1024  # 1MB — files under this use read_bytes, over use streaming
    term_len = len(term_bytes)

    def _check(s):
        try:
            size = s["size"]
            if size < _CHUNK:
                raw = s["file"].read_bytes().lower()
                if term_bytes not in raw:
                    return None
                return (s, raw.count(term_bytes))
            # Stream large files in overlapping chunks to avoid loading 100MB+ into memory
            count = 0
            with open(s["file"], "rb") as f:
                carry = b""
                while True:
                    chunk = f.read(_CHUNK)
                    if not chunk:
                        break
                    block = (carry + chunk).lower()
                    count += block.count(term_bytes)
                    # Keep tail overlap to catch matches spanning chunk boundaries
                    carry = chunk[-(term_len - 1):] if term_len > 1 else b""
            return (s, count) if count > 0 else None
        except OSError:
            return None

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(_check, all_sessions))

    matches = [r for r in results if r is not None]

    # Relevance score: 50% Poisson time decay + 50% √(matches)
    # Time decay: e^(-λt) where λ gives half-life of ~7 days
    now = time.time()
    _LAMBDA = math.log(2) / (7 * 86400)  # 7-day half-life
    max_sqrt = max((math.sqrt(c) for _, c in matches), default=1) or 1

    def _score(item):
        s, count = item
        age_s = max(now - s["mtime"], 0)
        time_score = math.exp(-_LAMBDA * age_s)
        freq_score = math.sqrt(count) / max_sqrt
        return 0.5 * time_score + 0.5 * freq_score

    matches.sort(key=_score, reverse=True)
    matches = matches[:limit]
    return [_session_row(s, {"matches": count, "score": round(_score((s, count)), 3)}) for s, count in matches]


@mcp.tool()
def read_session(
    session_id: str,
    keyword: str = "",
    limit: int = 10,
    mode: str = "summary",
) -> dict:
    """Read a Claude Code session. Use after search_sessions to drill in.

    Modes:
      - "summary": Returns cached AI summary if available (instant, cheap).
        If uncached, returns minimal context — call session_summary() to generate.
      - "messages": Returns head+tail user/assistant messages from the session.
        Optional keyword filters to only matching messages.
    """
    limit = max(1, min(limit, 30))
    session = _find_session(session_id)
    if session is None:
        return {"error": f"Session {session_id[:36]} not found"}

    if mode == "summary":
        ck = _cache.cache_key(session["file"])
        cached = _cache.get(session_id, ck, "summary")
        if not cached:
            # Try stale cache — title/summary still useful for active sessions
            data = _cache._read(session_id)
            cached = data.get("summary") if isinstance(data.get("summary"), dict) else None
        if cached:
            return {
                "id": session_id,
                "project": shorten_path(session["project_dir"]),
                "date": datetime.fromtimestamp(session["mtime"]).strftime("%Y-%m-%d %H:%M"),
                "summary": cached,
            }
        return {
            "id": session_id,
            "project": shorten_path(session["project_dir"]),
            "date": datetime.fromtimestamp(session["mtime"]).strftime("%Y-%m-%d %H:%M"),
            "note": "No cached summary. Call session_summary() to generate one.",
        }

    elif mode == "messages":
        return _read_messages(session["file"], keyword, limit)

    return {"error": f"Unknown mode: {mode}. Use 'summary' or 'messages'."}


def _read_messages(session_file: Path, keyword: str, limit: int) -> dict:
    """Extract user+assistant text messages from a session JSONL."""
    messages = []
    keyword_lower = keyword.lower() if keyword else ""

    try:
        with open(session_file, "r", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if not isinstance(entry, dict):
                    continue
                entry_type = entry.get("type")
                if entry_type not in ("user", "assistant"):
                    continue

                msg = entry.get("message", {})
                if not isinstance(msg, dict):
                    continue
                content = msg.get("content", "")
                if isinstance(content, list):
                    texts = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            texts.append(block.get("text", ""))
                        elif isinstance(block, str):
                            texts.append(block)
                    content = "\n".join(texts)
                elif not isinstance(content, str):
                    continue

                if not content.strip():
                    continue

                if keyword_lower and keyword_lower not in content.lower():
                    continue

                messages.append({"role": entry_type, "text": _trunc(content)})
    except OSError as e:
        return {"error": f"Could not read session file: {e}"}

    total = len(messages)
    limit = max(limit, 1)
    half = limit // 2 or 1
    if total <= limit:
        selected = messages
    else:
        selected = messages[:half] + messages[-half:]

    result = {"total": total, "messages": selected}
    if total > limit:
        result["note"] = f"First {half} + last {half} shown. {total - limit} omitted."
    if keyword:
        result["filter"] = keyword
        if total == 0:
            result["note"] = "Keyword not found in user/assistant messages. It may appear in tool calls or system entries. Try without keyword to see all messages."
    return result


@mcp.tool()
def recent_sessions(hours: int = 24, limit: int = 10) -> list[dict]:
    """List recently active Claude Code sessions.

    Resume any session with: claude --resume <id>
    """
    limit = max(1, min(limit, 25))
    sessions = find_recent_sessions(hours, max_sessions=limit)
    return [_session_row(s) for s in sessions]


@mcp.tool()
def session_summary(session_id: str, force_regenerate: bool = False) -> dict:
    """Get or generate an AI summary for a session.

    Returns cached summary instantly. If uncached, queues to the background
    daemon (returns in ~15s) or generates synchronously (~30s fallback).
    """
    session = _find_session(session_id)
    if session is None:
        return {"error": f"Session {session_id[:36]} not found"}

    session_file = session["file"]
    ck = _cache.cache_key(session_file)

    if not force_regenerate:
        cached = _cache.get(session_id, ck, "summary")
        if not cached:
            data = _cache._read(session_id)
            cached = data.get("summary") if isinstance(data.get("summary"), dict) else None
        if cached:
            return {"id": session_id, "source": "cache", **cached}

    # Prefer daemon — non-blocking
    if _daemon_alive():
        _queue_to_daemon(session_id, str(session_file), session["project_dir"])
        return {
            "id": session_id,
            "source": "queued",
            "note": "Queued to daemon. Call again in ~15s.",
        }

    # Fallback: synchronous generation
    context, search_text = parse_session(session_file)
    git = get_git_context(session["project_dir"])
    summary = summarize_quick(context, session["project_dir"], git)

    _cache.set(session_id, ck, "summary", summary)
    full = (search_text + f" {session['project_dir']} {session_id}").lower()
    _cache.set(session_id, ck, "search_text", full)

    return {"id": session_id, "source": "generated", **summary}


@mcp.tool()
def boot_up(hours: int = 24) -> dict:
    """Crash recovery: find interrupted Claude Code sessions that need attention.

    Detects sessions that were recently active but didn't exit cleanly —
    crashed terminals, killed processes, laptop sleep/restart, etc.
    Returns a prioritized list scored by urgency (recency + dirty files).

    Use after a reboot, crash, or "what was I working on?" moment.
    Resume any session with: claude --resume <id>
    """
    import subprocess

    hours = max(1, min(hours, 168))  # 1h to 7d
    now = time.time()
    cutoff = now - hours * 3600
    _LAMBDA = math.log(2) / (2 * 3600)  # 2-hour half-life (urgency, not search)

    # 1. Find sessions modified within the window
    recent = [s for s in find_all_sessions() if s["mtime"] >= cutoff]

    # 2. Find currently running claude processes and extract session IDs
    running_ids = set()
    try:
        ps = subprocess.run(
            ["ps", "aux"], capture_output=True, text=True, timeout=5
        )
        for line in ps.stdout.splitlines():
            if "--resume" in line:
                m = _UUID_RE.search(line)
                if m:
                    running_ids.add(m.group())
            elif "claude" in line and ".jsonl" in line:
                m = _UUID_RE.search(line)
                if m:
                    running_ids.add(m.group())
    except (subprocess.TimeoutExpired, OSError):
        pass

    # 3. Load all bookmarks
    bookmarks_dir = Path.home() / ".claude" / "bookmarks"
    bookmarks = {}
    if bookmarks_dir.exists():
        for bf in bookmarks_dir.glob("*-bookmark.json"):
            try:
                data = json.loads(bf.read_text())
                sid = data.get("session_id", "")
                if sid:
                    bookmarks[sid] = data
            except (json.JSONDecodeError, OSError):
                continue

    # 4. Classify each session
    sessions = []
    for s in recent:
        sid = s["session_id"]

        # Skip currently running sessions
        if sid in running_ids:
            continue

        bookmark = bookmarks.get(sid)
        lifecycle = bookmark.get("lifecycle_state", "") if bookmark else ""

        # Clean exits — skip
        if lifecycle in ("done", "paused", "blocked", "handing-off"):
            continue

        # Only recent sessions are plausible crash candidates.
        # Old sessions without bookmarks predate the bookmark system.
        # Old auto-closed sessions were already dealt with.
        age_h = (now - s["mtime"]) / 3600
        if not bookmark and age_h > 6:
            continue
        if lifecycle == "auto-closed" and age_h > 12:
            continue

        # What's left: recent auto-closed, or recent no-bookmark
        ws = bookmark.get("workspace_state", {}) if bookmark else {}
        dirty = ws.get("dirty", False)
        uncommitted = ws.get("uncommitted_files", [])
        last_commit = ws.get("last_commit", "")
        branch = bookmark.get("project", {}).get("git_branch", "") if bookmark else ""

        # Context: prefer cached title (richer), fall back to bookmark summary
        context_summary = _get_title(sid, s["file"])
        if not context_summary and bookmark:
            context_summary = bookmark.get("context", {}).get("summary", "")

        # Urgency score: exponential decay (2h half-life) + dirty file boost
        age_s = max(now - s["mtime"], 0)
        time_score = math.exp(-_LAMBDA * age_s)
        dirty_boost = 0.2 if dirty else 0
        file_boost = min(0.15, len(uncommitted) * 0.03) if uncommitted else 0
        score = time_score + dirty_boost + file_boost

        state = "crashed" if not bookmark else "interrupted"
        if lifecycle == "auto-closed":
            state = "auto-closed"

        row = {
            "id": sid,
            "project": shorten_path(s["project_dir"]),
            "date": datetime.fromtimestamp(s["mtime"]).strftime("%Y-%m-%d %H:%M"),
            "state": state,
            "summary": _trunc(context_summary, 100),
            "score": round(score, 3),
        }
        if dirty:
            row["dirty"] = True
            row["uncommitted_files"] = uncommitted[:10]
        if branch:
            row["branch"] = branch
        if last_commit:
            row["last_commit"] = last_commit

        sessions.append(row)

    # Sort by urgency score descending
    sessions.sort(key=lambda x: x["score"], reverse=True)

    return {
        "total": len(sessions),
        "running": len(running_ids),
        "checked": len(recent),
        "sessions": sessions[:15],
    }


@mcp.tool()
def resume_in_terminal(session_id: str) -> dict:
    """Launch a Claude --resume session in a new iTerm2 window.

    Opens iTerm2, cd's to the project directory, and runs
    claude --resume <id> --dangerously-skip-permissions.
    Use after boot_up() to quickly resume interrupted sessions.
    """
    import subprocess

    session = _find_session(session_id)
    if session is None:
        return {"error": f"Session {session_id[:36]} not found"}

    project_dir = session["project_dir"]
    title = _get_title(session_id, session["file"]) or project_dir

    # AppleScript to open iTerm2 with the resume command
    script = f'''
    tell application "iTerm2"
        activate
        set newWindow to (create window with default profile)
        tell current session of newWindow
            write text "cd {project_dir}"
            write text "claude --resume {session_id} --dangerously-skip-permissions"
        end tell
    end tell
    '''

    try:
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        return {"error": f"Failed to launch iTerm2: {e}"}

    return {
        "launched": True,
        "session_id": session_id,
        "project": shorten_path(project_dir),
        "title": _trunc(title, 80),
    }


@mcp.tool()
def merge_context(
    session_id: str,
    mode: str = "hybrid",
    keyword: str = "",
    message_limit: int = 6,
) -> dict:
    """Import context from another Claude Code session into this one.

    Use this to pull in research, decisions, or progress from a previous
    session without copy-pasting. The returned context is formatted for
    direct consumption — Claude understands it as imported session data.

    Modes:
      - "summary": AI-generated summary only (~1-2k tokens). Fast, compact.
      - "messages": Head+tail user/assistant messages (~1-5k tokens). Richer.
      - "hybrid": Summary + last few messages (~2-4k tokens). Best default.

    Optional keyword filter narrows messages to only matching content.
    """
    session = _find_session(session_id)
    if session is None:
        return {"error": f"Session {session_id[:36]} not found"}

    message_limit = max(2, min(message_limit, 20))
    project = shorten_path(session["project_dir"])
    date = datetime.fromtimestamp(session["mtime"]).strftime("%Y-%m-%d %H:%M")

    # --- Gather summary ---
    summary = None
    if mode in ("summary", "hybrid"):
        ck = _cache.cache_key(session["file"])
        summary = _cache.get(session_id, ck, "summary")
        if not summary:
            data = _cache._read(session_id)
            summary = data.get("summary") if isinstance(data.get("summary"), dict) else None

    # --- Gather messages ---
    msgs = None
    msgs_total = 0
    if mode in ("messages", "hybrid"):
        msg_limit = message_limit if mode == "messages" else min(message_limit, 6)
        raw = _read_messages(session["file"], keyword, msg_limit)
        if "messages" in raw:
            msgs = raw["messages"]
            msgs_total = raw.get("total", len(msgs))

    # --- Gather bookmark ---
    bookmark = None
    bookmark_file = Path.home() / ".claude" / "bookmarks" / f"{session_id}-bookmark.json"
    if bookmark_file.exists():
        try:
            bm = json.loads(bookmark_file.read_text())
            bookmark = {}
            ctx = bm.get("context", {})
            if ctx.get("summary"):
                bookmark["summary"] = ctx["summary"]
            if ctx.get("next_actions"):
                bookmark["next_actions"] = ctx["next_actions"][:5]
            ws = bm.get("workspace_state", {})
            if ws.get("uncommitted_files"):
                bookmark["uncommitted_files"] = ws["uncommitted_files"][:10]
            if bm.get("lifecycle_state"):
                bookmark["lifecycle_state"] = bm["lifecycle_state"]
            if not bookmark:
                bookmark = None
        except (json.JSONDecodeError, OSError):
            pass

    # --- Format context block ---
    lines = [f"## Imported Context from Session: {session_id[:8]}"]
    lines.append(f"**Project:** {project}  |  **Date:** {date}")

    if summary:
        if summary.get("title"):
            lines.append(f"**Title:** {summary['title']}")
        if summary.get("goal"):
            lines.append(f"**Goal:** {summary['goal']}")
        if summary.get("what_was_done"):
            lines.append(f"**Progress:** {summary['what_was_done']}")
        if summary.get("state"):
            lines.append(f"**State:** {summary['state']}")
        if summary.get("files"):
            lines.append(f"**Key Files:** {', '.join(summary['files'][:8])}")
        if summary.get("decisions_made"):
            lines.append("**Decisions:** " + "; ".join(summary["decisions_made"][:5]))
        if summary.get("next_steps"):
            lines.append(f"**Next Steps:** {summary['next_steps']}")

    if bookmark:
        lines.append("")
        if bookmark.get("lifecycle_state"):
            lines.append(f"**Session State:** {bookmark['lifecycle_state']}")
        if bookmark.get("next_actions"):
            lines.append("**Planned Actions:** " + "; ".join(bookmark["next_actions"]))
        if bookmark.get("uncommitted_files"):
            lines.append(f"**Uncommitted Files:** {', '.join(bookmark['uncommitted_files'])}")

    if msgs:
        lines.append("")
        lines.append("### Recent Conversation")
        for m in msgs:
            role = "User" if m["role"] == "user" else "Assistant"
            lines.append(f"**{role}:** {m['text']}")

    lines.append("")
    lines.append("---")
    lines.append("*Context imported via claude-resume merge. Continue from above.*")

    context_block = "\n".join(lines)

    result = {
        "session_id": session_id,
        "project": project,
        "date": date,
        "mode": mode,
        "context": context_block,
        "has_summary": summary is not None,
        "has_bookmark": bookmark is not None,
        "has_messages": msgs is not None,
    }
    if msgs is not None:
        result["messages_included"] = len(msgs)
        result["messages_total"] = msgs_total
    if keyword:
        result["keyword_filter"] = keyword
    if summary is None and mode in ("summary", "hybrid"):
        result["note"] = "No cached summary. Call session_summary() first for richer context, or use mode='messages'."

    return result


def main():
    if "--install" in sys.argv:
        snippet = {
            "mcpServers": {
                "claude-resume": {
                    "command": "claude-resume-mcp",
                    "args": [],
                }
            }
        }
        print("Add this to ~/.claude/settings.json:\n")
        print(json.dumps(snippet, indent=2))
        print("\nThen restart Claude Code.")
        return
    mcp.run()
