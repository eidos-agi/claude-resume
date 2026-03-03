"""CLI entry point for claude-resume."""

import os
import subprocess
import sys
import termios

from .sessions import (
    SessionCache,
    SessionOps,
    find_all_sessions,
    find_recent_sessions,
    get_git_context,
    get_label_deep,
    interruption_score,
    parse_session,
    relative_time,
    shorten_path,
    MAX_SESSIONS_ALL,
)
from claude_session_commons.summarize import analyze_patterns, summarize_deep, summarize_quick
from .ui import SessionPickerApp

DEFAULT_HOURS = 4

USAGE = """\
claude-resume — Post-crash Claude Code session picker.

Finds your most recently active Claude Code sessions, uses AI to summarize
what each one was doing, and copies the resume command to your clipboard.

Usage:
    claude-resume              # Show sessions from last 4 hours
    claude-resume 24           # Show sessions from last 24 hours
    claude-resume --all        # Show all sessions (up to 200)
    claude-resume --cache-all  # Background-index every session you've ever had
    claude-resume --search <term>  # Search all sessions for a keyword
"""


def _copy_to_clipboard(text: str):
    subprocess.run(["pbcopy"], input=text.encode(), check=True)


def _open_iterm_tabs(commands: list[str]):
    """Open each command in a new iTerm tab."""
    for cmd in commands:
        # Escape double quotes and backslashes for AppleScript
        escaped = cmd.replace("\\", "\\\\").replace('"', '\\"')
        script = f'''
        tell application "iTerm"
            activate
            tell current window
                create tab with default profile
                tell current session
                    write text "{escaped}"
                end tell
            end tell
        end tell
        '''
        subprocess.run(["osascript", "-e", script], capture_output=True)


def _daemon_alive() -> bool:
    """Check if the session daemon is running."""
    pid_file = os.path.join(os.path.expanduser("~"), ".claude", "session-daemon.pid")
    try:
        if not os.path.exists(pid_file):
            return False
        with open(pid_file) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return True
    except (ValueError, ProcessLookupError, PermissionError, OSError):
        return False


def _search_sessions(term: str):
    """Brute-force search all JSONL session files for a keyword."""
    from concurrent.futures import ThreadPoolExecutor
    from datetime import datetime

    term_bytes = term.lower().encode("utf-8", errors="replace")
    all_sessions = find_all_sessions()  # already sorted by mtime desc

    print(f"\n  Searching {len(all_sessions)} sessions for \033[1m{term}\033[0m...", end="", flush=True)

    def _check(s):
        try:
            raw = s["file"].read_bytes()
        except OSError:
            return None
        raw_lower = raw.lower()
        if term_bytes not in raw_lower:
            return None
        return (s, raw_lower.count(term_bytes))

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(_check, all_sessions))

    matches = [r for r in results if r is not None]

    print(f" done.\n")

    for i, (s, count) in enumerate(matches, 1):
        dt = datetime.fromtimestamp(s["mtime"])
        age = relative_time(s["mtime"])
        project = shorten_path(s["project_dir"])
        sid = s["session_id"]
        resume_cmd = f"claude --resume {sid}"
        count_str = f"{count} match{'es' if count != 1 else ''}"

        print(f"  \033[1;33m#{i}\033[0m  {dt:%Y-%m-%d %H:%M}  ({age})")
        print(f"      Project:  {project}")
        print(f"      Matches:  {count_str}")
        print(f"      Resume:   \033[36m{resume_cmd}\033[0m")
        print()

    if not matches:
        print(f"  No sessions found containing \"{term}\".\n")
    else:
        print(f"  \033[1;32m{len(matches)} session{'s' if len(matches) != 1 else ''} found.\033[0m\n")


def _cache_all_sessions():
    """Background-index every session that doesn't have a cached summary."""
    import json
    from pathlib import Path

    cache = SessionCache()
    all_sessions = find_all_sessions()

    # Count uncached
    uncached = []
    for s in all_sessions:
        ck = cache.cache_key(s["file"])
        if not cache.get(s["session_id"], ck, "summary"):
            uncached.append(s)

    cached = len(all_sessions) - len(uncached)

    if not uncached:
        print(f"\n  All {len(all_sessions)} sessions already cached.\n")
        return

    # If daemon is alive, write task files and let it handle everything
    if _daemon_alive():
        task_dir = Path.home() / ".claude" / "daemon-tasks"
        task_dir.mkdir(parents=True, exist_ok=True)
        for s in uncached:
            import time
            priority = int(time.time() * 1000)
            filename = f"{priority}-summarize-{s['session_id'][:8]}.json"
            task = {
                "kind": "summarize",
                "session_id": s["session_id"],
                "file": str(s["file"]),
                "project_dir": s["project_dir"],
                "quick_summary": None,
            }
            (task_dir / filename).write_text(json.dumps(task))
            time.sleep(0.001)  # ensure unique timestamps
        print(f"\n  Daemon is running — queued {len(uncached)} sessions for processing.")
        print(f"  ({cached} already cached)")
        print(f"  Monitor: tail -f ~/.claude/daemon.log\n")
        return

    # Fallback: local processing (daemon not running)
    total = len(all_sessions)
    generated = 0
    failed = 0

    print(f"\n  Daemon not running — indexing {len(uncached)} sessions locally...\n", flush=True)

    for i, s in enumerate(uncached, 1):
        ck = cache.cache_key(s["file"])
        short = shorten_path(s["project_dir"])
        age = relative_time(s["mtime"])
        print(f"  [{i}/{len(uncached)}] {short} ({age})...", end="", flush=True)

        try:
            context, search_text = parse_session(s["file"])
            git = get_git_context(s["project_dir"])
            summary = summarize_quick(context, s["project_dir"], git)
            cache.set(s["session_id"], ck, "summary", summary)
            full = (search_text + f" {s['project_dir']} {s['session_id']}").lower()
            cache.set(s["session_id"], ck, "search_text", full)
            get_label_deep(s["file"], cache)
            title = summary.get("title", "?")
            print(f" \033[32m{title}\033[0m", flush=True)
            generated += 1
        except Exception as e:
            print(f" \033[31mfailed: {e}\033[0m", flush=True)
            failed += 1

    print(f"\n  Done. {cached} already cached, {generated} newly indexed, {failed} failed.\n")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--cache-all":
        _cache_all_sessions()
        sys.exit(0)

    if len(sys.argv) > 1 and sys.argv[1] == "--search":
        if len(sys.argv) < 3:
            print("Usage: claude-resume --search <term>")
            sys.exit(1)
        _search_sessions(" ".join(sys.argv[2:]))
        sys.exit(0)

    hours = DEFAULT_HOURS
    show_all = False
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == "--all":
            hours = 8760
            show_all = True
        elif arg in ("--help", "-h"):
            print(USAGE)
            sys.exit(0)
        else:
            try:
                hours = float(arg)
            except ValueError:
                print("Usage: claude-resume [hours|--all|--cache-all|--search <term>]")
                sys.exit(1)

    max_sessions = MAX_SESSIONS_ALL if show_all else None
    sessions = find_recent_sessions(hours, max_sessions=max_sessions) if max_sessions else find_recent_sessions(hours)

    if not sessions:
        print(f"  No sessions found in the last {int(hours)} hours.")
        print("  Try: claude-resume --all")
        sys.exit(0)

    # Sort by date group first (preserves grouping), then by interruption score within each group
    from .sessions import get_date_group as _get_date_group
    group_order = {"Today": 0, "Yesterday": 1, "Last 7 Days": 2, "Last 30 Days": 3, "Older": 4}
    sessions.sort(key=lambda s: (group_order.get(_get_date_group(s["mtime"]), 9), -interruption_score(s)))

    cache = SessionCache()
    ops = SessionOps(
        cache=cache,
        parse_session=parse_session,
        get_git_context=get_git_context,
        summarize_quick=summarize_quick,
        summarize_deep=summarize_deep,
        analyze_patterns=analyze_patterns,
    )

    summaries = []
    for s in sessions:
        ck = cache.cache_key(s["file"])
        cached = cache.get(s["session_id"], ck, "summary")
        summaries.append(cached)

    termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)

    app = SessionPickerApp(sessions, summaries, ops)
    app.run()

    if not app.result_data:
        sys.exit(0)

    action, idx, cmd = app.result_data

    if action == "resume":
        # Exec directly into the session — replaces this process
        print(f"\n  \033[1;32m⟶ Resuming session...\033[0m\n")
        os.execlp("bash", "bash", "-c", cmd)

    elif action == "multi_resume":
        # cmd is a list of commands — open each in an iTerm tab
        cmds = cmd  # it's a list
        _open_iterm_tabs(cmds)
        print(f"\n  \033[1;32m✓ Opened {len(cmds)} sessions in iTerm tabs\033[0m\n")

    elif action == "select":
        _copy_to_clipboard(cmd)
        print(f"\n  \033[1;32m✓ Copied to clipboard:\033[0m")
        print(f"    {cmd}\n")
