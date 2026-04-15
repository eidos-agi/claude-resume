"""A1 + A2 — the autonomous AI management stack.

A1: product-improvement AI. Reads telemetry insights, writes recommendations.
    Auto-applies the 'auto' class (threshold edits only in v1). Queued class
    is filed for A2 / future human attention.

A2: process-management AI. Reads A1's prompt, A1's output, A1's auto-applied
    history, and A2's own prior proposal verdicts. Writes proposals for
    methodology changes to A1 (prompt diffs, threshold changes, criterion
    adds/removes).

Both use `claude -p` (fixed-cost per HARD CONSTRAINTS).

Storage:
  ~/.resume-resume/meta-ai/<user>/a1_recommendations.jsonl  (A1 output, event-sourced)
  ~/.resume-resume/meta-ai/<user>/a2_proposals.jsonl        (A2 output, event-sourced)
  ~/.resume-resume/meta-ai/<user>/a1_auto_applied.jsonl     (what A1 did to the config)
"""

from __future__ import annotations

import getpass
import json
import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from . import telemetry_query as tq


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PACKAGE_ROOT = Path(__file__).parent
A1_PROMPT_FILE = PACKAGE_ROOT / "a1_prompt.md"
A2_PROMPT_FILE = PACKAGE_ROOT / "a2_prompt.md"
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
# Generic event-sourced JSONL store
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
    """Collapse append-only log into the latest event per id."""
    latest: dict[str, dict] = {}
    for event in _iter(path):
        rid = event.get("id")
        if rid:
            latest[rid] = event
    return latest


# ---------------------------------------------------------------------------
# Thresholds config (shared between A1's auto-apply and telemetry_query)
# ---------------------------------------------------------------------------

def load_thresholds() -> dict:
    try:
        return json.loads(THRESHOLDS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "slow_tool_p95_ms": 1000,
            "error_prone_min_rate": 0.05,
            "error_prone_min_calls": 3,
            "dead_tool_divisor": 500,
            "a1_min_confidence": 0.6,
            "a2_min_confidence": 0.7,
            "abandoned_queries_limit": 20,
        }


def save_thresholds(data: dict) -> None:
    THRESHOLDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    THRESHOLDS_FILE.write_text(
        json.dumps(data, indent=2) + "\n", encoding="utf-8"
    )


_TUNABLE_KEYS = {
    "slow_tool_p95_ms",
    "error_prone_min_rate",
    "error_prone_min_calls",
    "dead_tool_divisor",
    "a1_min_confidence",
    "a2_min_confidence",
    "abandoned_queries_limit",
}


# ---------------------------------------------------------------------------
# LLM invocation — claude -p (fixed cost per HARD CONSTRAINTS)
# ---------------------------------------------------------------------------

def _run_claude(prompt: str, timeout: int = 180) -> str:
    result = subprocess.run(
        ["claude", "-p", prompt],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"claude -p failed (rc={result.returncode}): {result.stderr.strip()[:500]}"
        )
    return result.stdout


def _extract_json_array(text: str) -> list[dict]:
    text = text.strip()
    if not text:
        return []
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text).strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, list) else []
    except json.JSONDecodeError:
        pass
    match = re.search(r"\[[\s\S]*\]", text)
    if not match:
        return []
    try:
        obj = json.loads(match.group(0))
        return obj if isinstance(obj, list) else []
    except json.JSONDecodeError:
        return []


# ---------------------------------------------------------------------------
# A1 — product-improvement AI
# ---------------------------------------------------------------------------

def _compact_insights(days: int) -> dict:
    r = tq.insights_report(days=days)
    return {
        "days": r["days"],
        "total_calls": r["total_calls"],
        "total_errors": r["total_errors"],
        "overall_error_rate": r["overall_error_rate"],
        "distinct_tools": r["distinct_tools"],
        "usage": r["usage"],
        "dead_tools": [x["tool"] for x in r["dead_tools"]],
        "slow_tools": [
            {"tool": x["tool"], "p95_ms": x["p95_ms"], "count": x["count"]}
            for x in r["slow_tools"]
        ],
        "error_prone_tools": [
            {"tool": x["tool"], "error_rate": x["error_rate"], "count": x["count"]}
            for x in r["error_prone_tools"]
        ],
        "abandoned_query_count": len(r["abandoned_queries"]),
    }


def _recent_a1_titles(days: int = 30) -> list[dict]:
    cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
    out = []
    seen_ids: set[str] = set()
    for event in _iter(_a1_log()):
        rid = event.get("id")
        if not rid or rid in seen_ids:
            continue
        seen_ids.add(rid)
        try:
            ts = datetime.fromisoformat(
                (event.get("created_at") or "").replace("Z", "+00:00")
            ).timestamp()
        except ValueError:
            continue
        if ts < cutoff:
            continue
        out.append({
            "type": event.get("type"),
            "title": event.get("title"),
            "action_class": event.get("action_class"),
        })
    return out


def run_a1(days: int = 30) -> dict:
    """Invoke A1. Returns {created, auto_applied, skipped_*, items}."""
    thresholds = load_thresholds()
    prompt_body = A1_PROMPT_FILE.read_text(encoding="utf-8")
    payload = {
        "INSIGHTS": _compact_insights(days),
        "PRIOR_RECOMMENDATIONS": _recent_a1_titles(30),
        "CURRENT_THRESHOLDS": thresholds,
        "TUNABLE_KEYS": sorted(_TUNABLE_KEYS),
    }
    full_prompt = (
        prompt_body
        + "\n\n---\n\n# INPUT\n\n"
        + json.dumps(payload, default=str, indent=2)
    )

    raw = _run_claude(full_prompt)
    drafts = _extract_json_array(raw)

    existing = {(r.get("type"), (r.get("title") or "").strip().lower())
                for r in _recent_a1_titles(30)}

    min_conf = float(thresholds.get("a1_min_confidence", 0.6))
    created_items = []
    auto_applied = []
    skipped_low = 0
    skipped_dup = 0

    for d in drafts:
        if not isinstance(d, dict):
            continue
        title = (d.get("title") or "").strip()
        if not title:
            continue
        rtype = d.get("type") or "other"
        conf = float(d.get("confidence") or 0.0)
        if conf < min_conf:
            skipped_low += 1
            continue
        key = (rtype, title.lower())
        if key in existing:
            skipped_dup += 1
            continue

        rec = {
            "id": uuid.uuid4().hex[:12],
            "created_at": _now(),
            "agent": "A1",
            "type": rtype,
            "action_class": d.get("action_class") or "queued",
            "title": title,
            "evidence": d.get("evidence") or "",
            "confidence": round(max(0.0, min(1.0, conf)), 3),
            "target": d.get("target") or "",
            "new_value": d.get("new_value"),
            "suggested_action": d.get("suggested_action") or "",
            "state": "filed",
            "applied_at": None,
        }

        # Auto-apply guardrails: only tune + target in tunable keys + numeric new_value
        if (
            rec["action_class"] == "auto"
            and rec["type"] == "tune"
            and rec["target"] in _TUNABLE_KEYS
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
                auto_applied.append(rec)
            except Exception as e:
                rec["state"] = "auto_apply_failed"
                rec["error"] = str(e)
        else:
            # Downgrade anything else to queued — auto is a privilege
            if rec["action_class"] == "auto":
                rec["action_class"] = "queued"
                rec["note"] = "downgraded: target outside tunable keys or not numeric"

        _append(_a1_log(), rec)
        created_items.append(rec)
        existing.add(key)

    return {
        "created": len(created_items),
        "auto_applied": len(auto_applied),
        "skipped_low_confidence": skipped_low,
        "skipped_duplicate": skipped_dup,
        "total_drafts": len(drafts),
        "items": created_items,
        "auto_applied_items": auto_applied,
    }


# ---------------------------------------------------------------------------
# A2 — process-management AI
# ---------------------------------------------------------------------------

def _a1_recent_for_a2(days: int = 30) -> list[dict]:
    cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
    out = []
    for event in _iter(_a1_log()):
        try:
            ts = datetime.fromisoformat(
                (event.get("created_at") or "").replace("Z", "+00:00")
            ).timestamp()
        except ValueError:
            continue
        if ts < cutoff:
            continue
        out.append({
            "type": event.get("type"),
            "action_class": event.get("action_class"),
            "title": event.get("title"),
            "confidence": event.get("confidence"),
            "state": event.get("state"),
        })
    return out


def _a2_history(days: int = 90) -> list[dict]:
    current = _current(_a2_log())
    out = []
    cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
    for p in current.values():
        try:
            ts = datetime.fromisoformat(
                (p.get("created_at") or "").replace("Z", "+00:00")
            ).timestamp()
        except ValueError:
            continue
        if ts < cutoff:
            continue
        out.append({
            "target": p.get("target"),
            "change_type": p.get("change_type"),
            "title": p.get("title"),
            "state": p.get("state"),
            "decided_reason": p.get("decided_reason"),
        })
    return out


def run_a2(days: int = 30) -> dict:
    thresholds = load_thresholds()
    prompt_body = A2_PROMPT_FILE.read_text(encoding="utf-8")
    payload = {
        "A1_PROMPT": A1_PROMPT_FILE.read_text(encoding="utf-8"),
        "A1_RECOMMENDATIONS": _a1_recent_for_a2(days),
        "A1_AUTO_APPLIED": list(_iter(_applied_log())),
        "CURRENT_THRESHOLDS": thresholds,
        "INSIGHTS": _compact_insights(days),
        "PRIOR_A2_PROPOSALS": _a2_history(),
    }
    full_prompt = (
        prompt_body
        + "\n\n---\n\n# INPUT\n\n"
        + json.dumps(payload, default=str, indent=2)
    )

    raw = _run_claude(full_prompt)
    drafts = _extract_json_array(raw)

    min_conf = float(thresholds.get("a2_min_confidence", 0.7))
    created = 0
    skipped_low = 0
    items = []

    existing_pending = [
        p for p in _current(_a2_log()).values()
        if p.get("state") == "pending"
    ]
    existing_keys = {
        (p.get("target"), (p.get("title") or "").strip().lower())
        for p in existing_pending
    }

    for d in drafts:
        if not isinstance(d, dict):
            continue
        title = (d.get("title") or "").strip()
        target = d.get("target") or ""
        if not title or not target:
            continue
        conf = float(d.get("confidence") or 0.0)
        if conf < min_conf:
            skipped_low += 1
            continue
        key = (target, title.lower())
        if key in existing_keys:
            continue

        proposal = {
            "id": uuid.uuid4().hex[:12],
            "created_at": _now(),
            "agent": "A2",
            "target": target,
            "change_type": d.get("change_type") or "other",
            "title": title,
            "evidence": d.get("evidence") or "",
            "confidence": round(max(0.0, min(1.0, conf)), 3),
            "diff": d.get("diff"),
            "expected_effect": d.get("expected_effect") or "",
            "state": "pending",
            "decided_at": None,
            "decided_reason": None,
            "applied_at": None,
            "apply_error": None,
        }
        _append(_a2_log(), proposal)
        existing_keys.add(key)
        items.append(proposal)
        created += 1

    return {
        "created": created,
        "skipped_low_confidence": skipped_low,
        "total_drafts": len(drafts),
        "items": items,
    }


# ---------------------------------------------------------------------------
# Human inbox — only A2 proposals
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
    """Human verdict on an A2 proposal.

    On 'approved': try to apply the change (edit prompt file, update threshold).
    Leaves the working tree dirty — user commits manually.
    """
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


def _apply_proposal(proposal: dict) -> None:
    """Execute an approved A2 proposal by modifying files on disk."""
    target = proposal.get("target")
    change_type = proposal.get("change_type")
    diff = proposal.get("diff")

    if target == "thresholds.json" and change_type == "threshold_change":
        if not isinstance(diff, dict):
            raise ValueError("threshold_change expects diff={key, from, to}")
        key = diff.get("key")
        new_val = diff.get("to")
        if key not in _TUNABLE_KEYS:
            raise ValueError(f"threshold key {key!r} not tunable")
        if not isinstance(new_val, (int, float)):
            raise ValueError(f"threshold value must be numeric")
        cfg = load_thresholds()
        cfg[key] = new_val
        save_thresholds(cfg)
        return

    if target == "a1_prompt" and change_type == "prompt_edit":
        # diff is expected to be a unified-diff-ish string or a full replacement.
        # V1: expect diff to be a dict {"full_new_text": "..."} or just a string
        # that fully replaces the prompt. Anything else → apply_error.
        if isinstance(diff, dict) and "full_new_text" in diff:
            A1_PROMPT_FILE.write_text(diff["full_new_text"], encoding="utf-8")
            return
        if isinstance(diff, str) and diff.strip().startswith("# A1"):
            # Full file replacement
            A1_PROMPT_FILE.write_text(diff, encoding="utf-8")
            return
        raise ValueError(
            "prompt_edit requires diff as dict with 'full_new_text' "
            "or a string starting with '# A1' (full replacement)"
        )

    # Unknown target/type — approval recorded but no file action
    raise ValueError(f"unsupported proposal: target={target} change_type={change_type}")


# ---------------------------------------------------------------------------
# Read-side helpers for MCP tools
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
