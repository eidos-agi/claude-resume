"""Session discovery, JSONL parsing, and caching.

Thin wrapper around claude-session-commons. All shared logic lives
in the commons package; this file adds resume-specific pieces and
backward-compatible defaults.
"""

from pathlib import Path

from claude_session_commons import SessionCache as _BaseSessionCache
from claude_session_commons import (
    classify_session,
    decode_project_path,
    export_context_md,
    find_all_sessions,
    find_recent_sessions,
    format_duration,
    get_date_group,
    get_git_context,
    get_label,
    get_label_deep,
    get_tail_info,
    has_uncommitted_changes,
    interruption_score,
    parse_session,
    quick_scan,
    relative_time,
    shorten_path,
)
from claude_session_commons.discovery import (
    MAX_SESSIONS_DEFAULT,
    PROJECTS_DIR,
)
from claude_session_commons.cache import COOLDOWN_SECONDS

# Backward-compatible constants
MAX_SESSIONS_ALL = MAX_SESSIONS_DEFAULT
MIN_SESSION_BYTES = 100

CLAUDE_DIR = Path.home() / ".claude"
RESUME_CACHE_DIR = CLAUDE_DIR / "resume-summaries"


class SessionCache(_BaseSessionCache):
    """Resume-specific SessionCache defaulting to ~/.claude/resume-summaries/.

    Preserves backward compatibility with existing cached summaries.
    """

    def __init__(self, cache_dir: Path | None = None):
        super().__init__(cache_dir or RESUME_CACHE_DIR)


# Re-export SessionOps from commons for backward compat
from claude_session_commons.tui.ops import SessionOps  # noqa: E402


__all__ = [
    "SessionCache",
    "SessionOps",
    "classify_session",
    "decode_project_path",
    "export_context_md",
    "find_all_sessions",
    "find_recent_sessions",
    "format_duration",
    "get_date_group",
    "get_git_context",
    "get_label",
    "get_label_deep",
    "get_tail_info",
    "has_uncommitted_changes",
    "interruption_score",
    "parse_session",
    "quick_scan",
    "relative_time",
    "shorten_path",
    "CLAUDE_DIR",
    "COOLDOWN_SECONDS",
    "MAX_SESSIONS_ALL",
    "MAX_SESSIONS_DEFAULT",
    "MIN_SESSION_BYTES",
    "PROJECTS_DIR",
    "RESUME_CACHE_DIR",
]
