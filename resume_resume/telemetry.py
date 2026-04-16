"""Telemetry middleware for resume-resume MCP server.

Captures every MCP tool call (full args, full result, timing, errors) to
a per-user JSONL file so resume-resume can answer questions about its own
usage and we can learn what to improve next.

Storage: ~/.resume-resume/telemetry/<username>/YYYY-MM-DD.jsonl
Disable: RESUME_RESUME_TELEMETRY=0
"""

from __future__ import annotations

import getpass
import json
import os
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastmcp.server.middleware import Middleware, MiddlewareContext


def telemetry_enabled() -> bool:
    return os.environ.get("RESUME_RESUME_TELEMETRY", "1") != "0"


def telemetry_root() -> Path:
    return Path.home() / ".resume-resume" / "telemetry" / getpass.getuser()


def _today_path(root: Path | None = None) -> Path:
    root = root or telemetry_root()
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return root / f"{day}.jsonl"


def _safe_size(obj: Any) -> int:
    try:
        return len(json.dumps(obj, default=str))
    except Exception:
        return -1


def _jsonable(obj: Any) -> Any:
    """Coerce anything to something json.dumps can handle.

    Tool results can contain MCP content objects, pydantic models, dataclasses,
    bytes, or arbitrary objects. We want telemetry capture to never fail.
    """
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        pass

    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump()
        except Exception:
            pass
    if hasattr(obj, "dict") and callable(obj.dict):
        try:
            return obj.dict()
        except Exception:
            pass
    if hasattr(obj, "__dict__"):
        try:
            return {k: _jsonable(v) for k, v in vars(obj).items()}
        except Exception:
            pass
    if isinstance(obj, (list, tuple)):
        return [_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    return repr(obj)


def write_event(event: dict, *, path: Path | None = None) -> None:
    """Append a telemetry event to today's per-user JSONL file.

    Also runs lightweight maintenance: gzips old files on the first write
    of the day. Never raises — telemetry must not break the MCP server.
    """
    try:
        target = path or _today_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, default=str, ensure_ascii=False)
        with target.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        # Lightweight maintenance — gzip + retention on first write of the day
        _maybe_rotate(target.parent)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Rotation: gzip files older than 7 days, delete beyond retention limit
# ---------------------------------------------------------------------------

_GZIP_AFTER_DAYS = 7
_ROTATE_SENTINEL: set[str] = set()  # per-process, per-directory dedup


def _maybe_rotate(root: Path) -> None:
    """Gzip .jsonl files older than 7 days. Delete beyond retention limit.

    Runs at most once per process per directory (sentinel set).
    Retention: controlled by RESUME_RESUME_TELEMETRY_RETENTION_DAYS env var.
    Default: no deletion (only gzip). Set to e.g. 90 to delete files older
    than 90 days.
    """
    import gzip as _gzip

    key = str(root)
    if key in _ROTATE_SENTINEL:
        return
    _ROTATE_SENTINEL.add(key)

    try:
        today = datetime.now(timezone.utc).date()
        retention_days = int(os.environ.get("RESUME_RESUME_TELEMETRY_RETENTION_DAYS", "0"))

        for f in sorted(root.glob("*.jsonl")):
            try:
                file_date_str = f.stem  # YYYY-MM-DD
                from datetime import date as _date
                file_date = _date.fromisoformat(file_date_str)
                age_days = (today - file_date).days
            except (ValueError, TypeError):
                continue

            # Gzip old raw files
            if age_days >= _GZIP_AFTER_DAYS:
                gz_path = f.with_suffix(".jsonl.gz")
                if not gz_path.exists():
                    try:
                        with f.open("rb") as src, _gzip.open(gz_path, "wb") as dst:
                            dst.writelines(src)
                        f.unlink()
                    except OSError:
                        continue
                else:
                    # gz already exists, remove the raw
                    f.unlink()

        # Retention: delete old .jsonl.gz files beyond limit
        if retention_days > 0:
            for f in sorted(root.glob("*.jsonl.gz")):
                try:
                    file_date_str = f.stem.replace(".jsonl", "")
                    from datetime import date as _date
                    file_date = _date.fromisoformat(file_date_str)
                    age_days = (today - file_date).days
                except (ValueError, TypeError):
                    continue
                if age_days > retention_days:
                    f.unlink()
    except Exception:
        pass


def _session_id(context: MiddlewareContext) -> str | None:
    ctx = getattr(context, "fastmcp_context", None)
    if ctx is None:
        return None
    try:
        if getattr(ctx, "request_context", None) is not None:
            return getattr(ctx, "session_id", None)
    except Exception:
        return None
    return None


def _request_id(context: MiddlewareContext) -> str | None:
    ctx = getattr(context, "fastmcp_context", None)
    if ctx is None:
        return None
    try:
        if getattr(ctx, "request_context", None) is not None:
            return str(getattr(ctx, "request_id", None))
    except Exception:
        return None
    return None


# Maximum bytes of serialized result to store in telemetry. Beyond this,
# store a truncation marker + the true size. Prevents recursive bloat when
# self_* tools return telemetry data that contains prior results which
# contain prior results... (O(n^2) growth observed in production: self_recent_calls
# hit 95s avg because each call's JSONL entry contained the full results of
# all prior calls).
_MAX_RESULT_BYTES = 10_000


def _truncate_result(result: Any) -> Any:
    """Return the result if it's under the size cap, else a truncation marker."""
    serialized = _jsonable(result)
    size = _safe_size(serialized)
    if size <= _MAX_RESULT_BYTES:
        return serialized
    return {
        "_truncated": True,
        "_result_size": size,
        "_preview": str(serialized)[:500],
    }


# Tools whose results are telemetry data — logging their full output
# creates circular bloat. Log only size + preview for these.
_SELF_TOOLS = frozenset({
    "self_insights", "self_recent_calls", "self_slow_calls", "self_errors",
    "self_search", "self_bundles", "self_a1_output", "self_a1_auto_applied",
    "self_process_proposals", "self_proposal_history", "self_a2_scorecard",
})


class TelemetryMiddleware(Middleware):
    """Capture every MCP tool call to per-user JSONL."""

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        if not telemetry_enabled():
            return await call_next(context)

        msg = context.message
        tool_name = getattr(msg, "name", None)
        args = getattr(msg, "arguments", None) or {}
        started_ns = time.perf_counter_ns()
        started_iso = datetime.now(timezone.utc).isoformat()

        status = "ok"
        error_type: str | None = None
        error_msg: str | None = None
        error_tb: str | None = None
        result: Any = None

        try:
            result = await call_next(context)
            return result
        except Exception as e:
            status = "error"
            error_type = type(e).__name__
            error_msg = str(e)
            error_tb = traceback.format_exc()
            raise
        finally:
            duration_ms = (time.perf_counter_ns() - started_ns) / 1_000_000

            # For self_* tools, always truncate to prevent recursive bloat.
            # For other tools, truncate only if result exceeds the cap.
            if status == "ok":
                result_size = _safe_size(result)
                if tool_name in _SELF_TOOLS:
                    logged_result = {
                        "_truncated": True,
                        "_result_size": result_size,
                        "_tool_is_self": True,
                    }
                else:
                    logged_result = _truncate_result(result)
            else:
                result_size = 0
                logged_result = None

            event = {
                "ts": started_iso,
                "session_id": _session_id(context),
                "request_id": _request_id(context),
                "tool": tool_name,
                "args": _jsonable(args),
                "duration_ms": round(duration_ms, 3),
                "status": status,
                "error_type": error_type,
                "error_msg": error_msg,
                "error_tb": error_tb,
                "result_size": result_size,
                "result": logged_result,
                "pid": os.getpid(),
            }
            write_event(event)
