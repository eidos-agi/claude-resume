"""Meta-AI stores, thresholds, and apply logic.

The A1 and A2 agents themselves are Claude Code skills at
`.claude/skills/resume-resume-a1/SKILL.md` and `.claude/skills/resume-resume-a2/SKILL.md`.
The skills run in the Claude Code agent loop and call MCP tools defined in
mcp_server.py (self_a1_file, self_a2_file, etc.) which delegate here.

This module is the *data layer*:
- JSONL stores for A1 recommendations, A2 proposals, A1 auto-apply audit.
- Thresholds config (shared between A1 auto-apply, A2 proposals, and
  telemetry_query.insights_report).
- Apply logic for approved A2 proposals (deterministic file edits).

No LLM invocation lives here anymore. Calling an LLM from inside an async
MCP server via blocking subprocess was the wrong shape; skills are the
right primitive.
"""

from __future__ import annotations

import getpass
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

# Find the repo root (where .claude/ lives) by walking up from this file.
def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for candidate in [p.parent, *p.parents]:
        if (candidate / ".claude" / "skills").exists():
            return candidate
        if (candidate / "pyproject.toml").exists():
            return candidate
    return p.parent.parent


PACKAGE_ROOT = Path(__file__).parent
REPO_ROOT = _repo_root()
A1_SKILL_FILE = REPO_ROOT / ".claude" / "skills" / "resume-resume-a1" / "SKILL.md"
A2_SKILL_FILE = REPO_ROOT / ".claude" / "skills" / "resume-resume-a2" / "SKILL.md"
# Backwards-compat alias — apply logic targets a1_prompt → SKILL.md
A1_PROMPT_FILE = A1_SKILL_FILE
THRESHOLDS_FILE = PACKAGE_ROOT / "config" / "thresholds.json"


def meta_root() -> Path:
    return Path.home() / ".resume-resume" / "meta-ai" / getpass.getuser()


def _a1_log() -> Path:
    return meta_root() / "a1_recommendations.jsonl"


def _a2_log() -> Path:
    return meta_root() / "a2_proposals.jsonl"


def _applied_log() -> Path:
    return meta_root() / "a1_auto_applied.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Event-sourced JSONL helpers
# ---------------------------------------------------------------------------

def _append(path: Path, event: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, default=str, ensure_ascii=False) + "\n")


def _iter(path: Path) -> Iterator[dict]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _current(path: Path) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for event in _iter(path):
        rid = event.get("id")
        if rid:
            latest[rid] = event
    return latest


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

_DEFAULT_THRESHOLDS = {
    "slow_tool_p95_ms": 1000,
    "error_prone_min_rate": 0.05,
    "error_prone_min_calls": 3,
    "dead_tool_divisor": 500,
    "a1_min_confidence": 0.6,
    "a2_min_confidence": 0.7,
    "abandoned_queries_limit": 20,
}


def load_thresholds() -> dict:
    try:
        return json.loads(THRESHOLDS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(_DEFAULT_THRESHOLDS)


def save_thresholds(data: dict) -> None:
    THRESHOLDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    THRESHOLDS_FILE.write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8"
    )


TUNABLE_KEYS = frozenset({
    "slow_tool_p95_ms",
    "error_prone_min_rate",
    "error_prone_min_calls",
    "dead_tool_divisor",
    "a1_min_confidence",
    "a2_min_confidence",
    "abandoned_queries_limit",
})


# ---------------------------------------------------------------------------
# A1 write side: called by the self_a1_file MCP tool (invoked by the A1 skill)
# ---------------------------------------------------------------------------

def file_a1_recommendation(
    *,
    type: str,
    title: str,
    evidence: str,
    confidence: float,
    action_class: str = "queued",
    target: str = "",
    new_value=None,
    suggested_action: str = "",
    dedupe_window_days: int = 30,
) -> dict:
    """File an A1 recommendation.

    Enforces confidence threshold, dedupes against recent entries, auto-applies
    threshold tweaks when guardrails pass, downgrades unsafe auto-requests to
    queued. Returns the recorded record (or a {skipped: ...} dict).
    """
    title = (title or "").strip()
    if not title:
        return {"skipped": "empty_title"}

    thresholds = load_thresholds()
    min_conf = float(thresholds.get("a1_min_confidence", 0.6))
    if confidence < min_conf:
        return {"skipped": "low_confidence", "min_confidence": min_conf}

    # Dedupe (type + title) within dedupe window
    cutoff = datetime.now(timezone.utc).timestamp() - dedupe_window_days * 86400
    for existing in _iter(_a1_log()):
        if existing.get("type") != type:
            continue
        if (existing.get("title") or "").strip().lower() != title.lower():
            continue
        try:
            ts = datetime.fromisoformat(
                (existing.get("created_at") or "").replace("Z", "+00:00")
            ).timestamp()
        except ValueError:
            continue
        if ts >= cutoff:
            return {"skipped": "duplicate", "existing_id": existing.get("id")}

    rec = {
        "id": uuid.uuid4().hex[:12],
        "created_at": _now(),
        "agent": "A1",
        "type": type,
        "action_class": action_class,
        "title": title,
        "evidence": evidence or "",
        "confidence": round(max(0.0, min(1.0, float(confidence))), 3),
        "target": target or "",
        "new_value": new_value,
        "suggested_action": suggested_action or "",
        "state": "filed",
        "applied_at": None,
    }

    # Auto-apply guardrails
    if (
        rec["action_class"] == "auto"
        and rec["type"] == "tune"
        and rec["target"] in TUNABLE_KEYS
        and isinstance(rec["new_value"], (int, float))
    ):
        try:
            before = thresholds.get(rec["target"])
            thresholds[rec["target"]] = rec["new_value"]
            save_thresholds(thresholds)
            rec["state"] = "auto_applied"
            rec["applied_at"] = _now()
            _append(_applied_log(), {
                "applied_at": rec["applied_at"],
                "a1_rec_id": rec["id"],
                "target": rec["target"],
                "before": before,
                "after": rec["new_value"],
                "evidence": rec["evidence"],
            })
        except Exception as e:
            rec["state"] = "auto_apply_failed"
            rec["error"] = str(e)
    elif rec["action_class"] == "auto":
        rec["action_class"] = "queued"
        rec["note"] = "downgraded: target outside TUNABLE_KEYS or new_value not numeric"

    _append(_a1_log(), rec)
    return rec


# ---------------------------------------------------------------------------
# A2 write side: called by self_a2_file MCP tool (invoked by A2 skill)
# ---------------------------------------------------------------------------

VALID_A2_TARGETS = frozenset({"a1_prompt", "thresholds.json", "cadence"})
VALID_A2_CHANGE_TYPES = frozenset({
    "prompt_edit", "threshold_change", "criterion_add", "criterion_remove",
    "authority_change", "other",
})


def file_a2_proposal(
    *,
    target: str,
    change_type: str,
    title: str,
    evidence: str,
    confidence: float,
    diff=None,
    expected_effect: str = "",
) -> dict:
    title = (title or "").strip()
    if not title:
        return {"skipped": "empty_title"}
    if target not in VALID_A2_TARGETS:
        return {"skipped": "invalid_target", "valid": sorted(VALID_A2_TARGETS)}
    if change_type not in VALID_A2_CHANGE_TYPES:
        return {"skipped": "invalid_change_type", "valid": sorted(VALID_A2_CHANGE_TYPES)}

    thresholds = load_thresholds()
    min_conf = float(thresholds.get("a2_min_confidence", 0.7))
    if confidence < min_conf:
        return {"skipped": "low_confidence", "min_confidence": min_conf}

    # Dedupe against currently-pending proposals (target + title)
    for p in _current(_a2_log()).values():
        if p.get("state") != "pending":
            continue
        if p.get("target") != target:
            continue
        if (p.get("title") or "").strip().lower() == title.lower():
            return {"skipped": "duplicate_pending", "existing_id": p.get("id")}

    proposal = {
        "id": uuid.uuid4().hex[:12],
        "created_at": _now(),
        "agent": "A2",
        "target": target,
        "change_type": change_type,
        "title": title,
        "evidence": evidence or "",
        "confidence": round(max(0.0, min(1.0, float(confidence))), 3),
        "diff": diff,
        "expected_effect": expected_effect or "",
        "state": "pending",
        "decided_at": None,
        "decided_reason": None,
        "applied_at": None,
        "apply_error": None,
    }
    _append(_a2_log(), proposal)
    return proposal


# ---------------------------------------------------------------------------
# Human inbox
# ---------------------------------------------------------------------------

def list_proposals(state: str = "pending", limit: int = 50) -> list[dict]:
    items = [p for p in _current(_a2_log()).values() if p.get("state") == state]
    items.sort(key=lambda p: p.get("created_at") or "", reverse=True)
    return items[:limit]


def proposal_history(limit: int = 100) -> list[dict]:
    items = [
        p for p in _current(_a2_log()).values()
        if p.get("state") in {"approved", "rejected", "deferred"}
    ]
    items.sort(key=lambda p: p.get("decided_at") or "", reverse=True)
    return items[:limit]


def decide_proposal(proposal_id: str, verdict: str, reason: str = "") -> dict:
    if verdict not in {"approved", "rejected", "deferred"}:
        raise ValueError(f"invalid verdict {verdict!r}")

    current = _current(_a2_log()).get(proposal_id)
    if not current:
        raise ValueError(f"no proposal with id {proposal_id!r}")

    updated = {
        **current,
        "state": verdict,
        "decided_at": _now(),
        "decided_reason": reason,
    }

    if verdict == "approved":
        try:
            _apply_proposal(updated)
            updated["applied_at"] = _now()
        except Exception as e:
            updated["apply_error"] = str(e)

    _append(_a2_log(), updated)
    return updated


def _coerce_diff(diff):
    """If diff arrived as a JSON-encoded string of a dict, decode it.

    MCP transport / tool-call serialization can turn a dict parameter into a
    JSON string. Apply logic wants the native dict shape. Best-effort decode;
    leaves non-JSON strings unchanged so the string branch still catches them.
    """
    if not isinstance(diff, str):
        return diff
    stripped = diff.strip()
    if not stripped or stripped[0] not in "{[":
        return diff
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, (dict, list)):
            return parsed
    except (json.JSONDecodeError, ValueError):
        pass
    return diff


def _apply_proposal(proposal: dict) -> None:
    target = proposal.get("target")
    change_type = proposal.get("change_type")
    diff = _coerce_diff(proposal.get("diff"))

    if target == "thresholds.json" and change_type == "threshold_change":
        if not isinstance(diff, dict):
            raise ValueError("threshold_change expects diff={key, from, to}")
        key = diff.get("key")
        new_val = diff.get("to")
        if key not in TUNABLE_KEYS:
            raise ValueError(f"threshold key {key!r} not tunable")
        if not isinstance(new_val, (int, float)):
            raise ValueError("threshold value must be numeric")
        cfg = load_thresholds()
        cfg[key] = new_val
        save_thresholds(cfg)
        return

    if target == "a1_prompt" and change_type == "prompt_edit":
        if isinstance(diff, dict) and "full_new_text" in diff:
            A1_PROMPT_FILE.write_text(diff["full_new_text"], encoding="utf-8")
            return
        if isinstance(diff, str) and diff.strip().startswith(("---", "# A1", "# ")):
            A1_PROMPT_FILE.write_text(diff, encoding="utf-8")
            return
        raise ValueError(
            "prompt_edit requires diff as dict with 'full_new_text' "
            "or a string starting with frontmatter or heading (full replacement)"
        )

    raise ValueError(f"unsupported proposal: target={target} change_type={change_type}")


# ---------------------------------------------------------------------------
# Read helpers for MCP tools
# ---------------------------------------------------------------------------

def a1_recent_recommendations(limit: int = 20, action_class: str | None = None) -> list[dict]:
    items: list[dict] = list(_iter(_a1_log()))
    if action_class:
        items = [x for x in items if x.get("action_class") == action_class]
    items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return items[:limit]


def a1_auto_applied_history(limit: int = 50) -> list[dict]:
    items = list(_iter(_applied_log()))
    items.sort(key=lambda x: x.get("applied_at") or "", reverse=True)
    return items[:limit]


def read_a1_prompt() -> str:
    """A2 reads A1's skill prompt to reason about methodology changes."""
    try:
        return A1_SKILL_FILE.read_text(encoding="utf-8")
    except OSError:
        return ""
