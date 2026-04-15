"""Tests for the meta-AI data layer.

The A1 and A2 agents are skills, not Python. These tests cover the
write-side API (file_a1_recommendation, file_a2_proposal), the store
semantics (event-sourced JSONL), the apply logic for approved proposals,
and threshold load/save.
"""

from __future__ import annotations

import json

import pytest

from resume_resume import meta_ai


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Point meta-AI storage + config + skill files at tmp_path."""
    monkeypatch.setattr(meta_ai, "meta_root", lambda: tmp_path / "meta")
    monkeypatch.setattr(meta_ai, "A1_SKILL_FILE", tmp_path / "a1_skill.md")
    monkeypatch.setattr(meta_ai, "A1_PROMPT_FILE", tmp_path / "a1_skill.md")
    monkeypatch.setattr(meta_ai, "A2_SKILL_FILE", tmp_path / "a2_skill.md")
    monkeypatch.setattr(meta_ai, "THRESHOLDS_FILE", tmp_path / "thresholds.json")
    (tmp_path / "a1_skill.md").write_text("---\nname: a1\n---\n# A1\nplaceholder\n")
    (tmp_path / "a2_skill.md").write_text("---\nname: a2\n---\n# A2\nplaceholder\n")
    meta_ai.save_thresholds({
        "slow_tool_p95_ms": 1000,
        "a1_min_confidence": 0.6,
        "a2_min_confidence": 0.7,
    })
    return tmp_path


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

def test_load_and_save_thresholds(isolated):
    t = meta_ai.load_thresholds()
    assert t["slow_tool_p95_ms"] == 1000
    meta_ai.save_thresholds({"slow_tool_p95_ms": 2500, "a1_min_confidence": 0.7})
    t2 = meta_ai.load_thresholds()
    assert t2["slow_tool_p95_ms"] == 2500


def test_load_thresholds_returns_defaults_if_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(meta_ai, "THRESHOLDS_FILE", tmp_path / "missing.json")
    t = meta_ai.load_thresholds()
    assert t["slow_tool_p95_ms"] == 1000  # from _DEFAULT_THRESHOLDS


# ---------------------------------------------------------------------------
# A1 filing
# ---------------------------------------------------------------------------

def test_file_a1_recommendation_basic(isolated):
    rec = meta_ai.file_a1_recommendation(
        type="optimize",
        title="Optimize dirty_repos",
        evidence="p95=3071ms",
        confidence=0.8,
        action_class="queued",
        suggested_action="add a cache",
    )
    assert rec["id"]
    assert rec["state"] == "filed"
    assert rec["action_class"] == "queued"
    assert rec["confidence"] == 0.8


def test_file_a1_auto_apply_happy_path(isolated):
    rec = meta_ai.file_a1_recommendation(
        type="tune",
        title="Raise slow threshold to 2500",
        evidence="19 of 23 flags were noise",
        confidence=0.85,
        action_class="auto",
        target="slow_tool_p95_ms",
        new_value=2500,
    )
    assert rec["state"] == "auto_applied"
    assert rec["applied_at"] is not None
    assert meta_ai.load_thresholds()["slow_tool_p95_ms"] == 2500

    applied = list(meta_ai._iter(meta_ai._applied_log()))
    assert len(applied) == 1
    assert applied[0]["before"] == 1000
    assert applied[0]["after"] == 2500


def test_file_a1_downgrades_unsafe_auto(isolated):
    # Code-change type with action_class=auto → must downgrade to queued
    rec = meta_ai.file_a1_recommendation(
        type="remove",
        title="Remove dirty_repos",
        evidence="0 calls in 30d",
        confidence=0.9,
        action_class="auto",
    )
    assert rec["action_class"] == "queued"
    assert "downgraded" in (rec.get("note") or "")


def test_file_a1_downgrades_non_numeric_new_value(isolated):
    rec = meta_ai.file_a1_recommendation(
        type="tune",
        title="Tune something weird",
        evidence="...",
        confidence=0.9,
        action_class="auto",
        target="slow_tool_p95_ms",
        new_value="not a number",  # type: ignore
    )
    assert rec["action_class"] == "queued"


def test_file_a1_downgrades_non_tunable_target(isolated):
    rec = meta_ai.file_a1_recommendation(
        type="tune",
        title="Tune a non-existent key",
        evidence="...",
        confidence=0.9,
        action_class="auto",
        target="not_a_real_key",
        new_value=42,
    )
    assert rec["action_class"] == "queued"
    # Thresholds must not have been modified
    assert "not_a_real_key" not in meta_ai.load_thresholds()


def test_file_a1_skips_low_confidence(isolated):
    result = meta_ai.file_a1_recommendation(
        type="tune",
        title="weak",
        evidence="meh",
        confidence=0.3,
    )
    assert result.get("skipped") == "low_confidence"


def test_file_a1_skips_empty_title(isolated):
    result = meta_ai.file_a1_recommendation(
        type="tune", title="   ", evidence="x", confidence=0.9,
    )
    assert result.get("skipped") == "empty_title"


def test_file_a1_dedupes_recent_duplicate(isolated):
    first = meta_ai.file_a1_recommendation(
        type="optimize", title="Optimize X", evidence="...", confidence=0.8,
    )
    second = meta_ai.file_a1_recommendation(
        type="optimize", title="optimize x", evidence="...", confidence=0.8,
    )
    assert first.get("id")
    assert second.get("skipped") == "duplicate"


# ---------------------------------------------------------------------------
# A2 filing
# ---------------------------------------------------------------------------

def test_file_a2_proposal_basic(isolated):
    p = meta_ai.file_a2_proposal(
        target="a1_prompt",
        change_type="criterion_add",
        title="Teach A1 regression detection",
        evidence="A1 missed w-over-w p95 growth",
        confidence=0.75,
        diff="add criterion: flag p95 growth ≥2× week-over-week",
        expected_effect="A1 will emit regression findings",
    )
    assert p["id"]
    assert p["state"] == "pending"


def test_file_a2_skips_invalid_target(isolated):
    result = meta_ai.file_a2_proposal(
        target="random_file", change_type="prompt_edit",
        title="x", evidence="x", confidence=0.9,
    )
    assert result.get("skipped") == "invalid_target"


def test_file_a2_skips_invalid_change_type(isolated):
    result = meta_ai.file_a2_proposal(
        target="a1_prompt", change_type="refactor_everything",
        title="x", evidence="x", confidence=0.9,
    )
    assert result.get("skipped") == "invalid_change_type"


def test_file_a2_skips_low_confidence(isolated):
    result = meta_ai.file_a2_proposal(
        target="a1_prompt", change_type="prompt_edit",
        title="x", evidence="x", confidence=0.5,
    )
    assert result.get("skipped") == "low_confidence"


def test_file_a2_dedupes_pending(isolated):
    first = meta_ai.file_a2_proposal(
        target="a1_prompt", change_type="criterion_add",
        title="Add thing", evidence="...", confidence=0.8,
    )
    second = meta_ai.file_a2_proposal(
        target="a1_prompt", change_type="criterion_add",
        title="add thing", evidence="...", confidence=0.8,
    )
    assert first.get("id")
    assert second.get("skipped") == "duplicate_pending"


# ---------------------------------------------------------------------------
# Decide + apply
# ---------------------------------------------------------------------------

def test_decide_approve_threshold_change(isolated):
    p = meta_ai.file_a2_proposal(
        target="thresholds.json", change_type="threshold_change",
        title="Raise slow threshold", evidence="rejections",
        confidence=0.85,
        diff={"key": "slow_tool_p95_ms", "from": 1000, "to": 2500},
    )
    out = meta_ai.decide_proposal(p["id"], "approved", reason="agree")
    assert out["state"] == "approved"
    assert out["apply_error"] is None
    assert meta_ai.load_thresholds()["slow_tool_p95_ms"] == 2500


def test_decide_approve_prompt_edit_dict_form(isolated):
    new_text = "---\nname: a1\n---\n# A1\nbrand new body\n"
    p = meta_ai.file_a2_proposal(
        target="a1_prompt", change_type="prompt_edit",
        title="Rewrite A1 prompt", evidence="clarity",
        confidence=0.9,
        diff={"full_new_text": new_text},
    )
    out = meta_ai.decide_proposal(p["id"], "approved")
    assert out["state"] == "approved"
    assert out["apply_error"] is None
    assert meta_ai.A1_PROMPT_FILE.read_text() == new_text


def test_decide_approve_prompt_edit_json_string_form(isolated):
    """MCP transport can turn a dict diff into a JSON-encoded string;
    _coerce_diff must decode it so apply doesn't fail."""
    new_text = "---\nname: a1\n---\n# A1\nfrom json string\n"
    p = meta_ai.file_a2_proposal(
        target="a1_prompt", change_type="prompt_edit",
        title="Rewrite via json string", evidence="transport artifact",
        confidence=0.9,
        diff=json.dumps({"full_new_text": new_text}),
    )
    out = meta_ai.decide_proposal(p["id"], "approved")
    assert out["state"] == "approved"
    assert out["apply_error"] is None
    assert meta_ai.A1_PROMPT_FILE.read_text() == new_text


def test_coerce_diff_passes_through_non_json_strings(isolated):
    # A bare markdown string should stay a string (for the string branch)
    raw = "---\nname: a1\n---\n# A1\nbare markdown\n"
    assert meta_ai._coerce_diff(raw) == raw


def test_coerce_diff_leaves_dict_alone(isolated):
    d = {"full_new_text": "x"}
    assert meta_ai._coerce_diff(d) is d


def test_coerce_diff_decodes_json_dict(isolated):
    result = meta_ai._coerce_diff('{"full_new_text": "abc"}')
    assert result == {"full_new_text": "abc"}


def test_decide_reject_does_not_apply(isolated):
    p = meta_ai.file_a2_proposal(
        target="thresholds.json", change_type="threshold_change",
        title="Nope", evidence="...", confidence=0.85,
        diff={"key": "slow_tool_p95_ms", "from": 1000, "to": 99999},
    )
    meta_ai.decide_proposal(p["id"], "rejected", reason="too aggressive")
    assert meta_ai.load_thresholds()["slow_tool_p95_ms"] == 1000


def test_decide_apply_records_error_on_non_tunable_key(isolated):
    # We can't reach here through file_a2_proposal (target validated by tests),
    # but we can inject a proposal directly via _append.
    proposal = {
        "id": "p-bad",
        "created_at": meta_ai._now(),
        "agent": "A2",
        "target": "thresholds.json",
        "change_type": "threshold_change",
        "title": "Bad key",
        "evidence": "...",
        "confidence": 0.9,
        "diff": {"key": "not_a_real_key", "to": 42},
        "expected_effect": "...",
        "state": "pending",
        "decided_at": None, "decided_reason": None,
        "applied_at": None, "apply_error": None,
    }
    meta_ai._append(meta_ai._a2_log(), proposal)
    out = meta_ai.decide_proposal("p-bad", "approved")
    assert out["state"] == "approved"
    assert "not tunable" in (out["apply_error"] or "")


def test_decide_unknown_id_raises(isolated):
    with pytest.raises(ValueError):
        meta_ai.decide_proposal("nope", "approved")


def test_decide_invalid_verdict_raises(isolated):
    with pytest.raises(ValueError):
        meta_ai.decide_proposal("any", "maybe")


def test_event_sourced_latest_state_wins(isolated):
    p = meta_ai.file_a2_proposal(
        target="thresholds.json", change_type="threshold_change",
        title="Thing", evidence="...", confidence=0.8,
        diff={"key": "slow_tool_p95_ms", "from": 1000, "to": 1500},
    )
    meta_ai.decide_proposal(p["id"], "deferred", reason="not now")
    pending = meta_ai.list_proposals(state="pending")
    deferred = meta_ai.list_proposals(state="deferred")
    assert not pending
    assert len(deferred) == 1
    assert deferred[0]["id"] == p["id"]


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------

def test_a1_recent_filters_by_action_class(isolated):
    meta_ai.file_a1_recommendation(
        type="tune", title="one", evidence="...", confidence=0.8,
        action_class="auto", target="slow_tool_p95_ms", new_value=1100,
    )
    meta_ai.file_a1_recommendation(
        type="optimize", title="two", evidence="...", confidence=0.8,
        action_class="queued",
    )
    auto = meta_ai.a1_recent_recommendations(action_class="auto")
    queued = meta_ai.a1_recent_recommendations(action_class="queued")
    assert len(auto) == 1 and auto[0]["title"] == "one"
    assert len(queued) == 1 and queued[0]["title"] == "two"


def test_read_a1_prompt_returns_skill_body(isolated):
    body = meta_ai.read_a1_prompt()
    assert "# A1" in body


def test_read_a1_prompt_returns_empty_if_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(meta_ai, "A1_SKILL_FILE", tmp_path / "no-such-file.md")
    assert meta_ai.read_a1_prompt() == ""
