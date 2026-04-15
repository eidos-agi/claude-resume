"""Tests for the meta-AI stack (A1 + A2 stores, apply logic, thresholds)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from resume_resume import meta_ai


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Point meta-AI storage + config at tmp_path so tests don't touch real state."""
    monkeypatch.setattr(meta_ai, "meta_root", lambda: tmp_path / "meta")
    monkeypatch.setattr(meta_ai, "A1_PROMPT_FILE", tmp_path / "a1_prompt.md")
    monkeypatch.setattr(meta_ai, "A2_PROMPT_FILE", tmp_path / "a2_prompt.md")
    monkeypatch.setattr(meta_ai, "THRESHOLDS_FILE", tmp_path / "thresholds.json")
    (tmp_path / "a1_prompt.md").write_text("# A1\n\nplaceholder prompt\n")
    (tmp_path / "a2_prompt.md").write_text("# A2\n\nplaceholder prompt\n")
    meta_ai.save_thresholds({
        "slow_tool_p95_ms": 1000,
        "a1_min_confidence": 0.6,
        "a2_min_confidence": 0.7,
    })
    return tmp_path


def test_load_and_save_thresholds(isolated):
    t = meta_ai.load_thresholds()
    assert t["slow_tool_p95_ms"] == 1000
    meta_ai.save_thresholds({"slow_tool_p95_ms": 2500, "a1_min_confidence": 0.7})
    t2 = meta_ai.load_thresholds()
    assert t2["slow_tool_p95_ms"] == 2500


def test_extract_json_array_plain():
    assert meta_ai._extract_json_array('[{"a": 1}]') == [{"a": 1}]


def test_extract_json_array_fenced():
    raw = '```json\n[{"a": 1}, {"b": 2}]\n```'
    assert meta_ai._extract_json_array(raw) == [{"a": 1}, {"b": 2}]


def test_extract_json_array_with_prose():
    raw = 'Here is the array:\n[{"a": 1}]\nThanks.'
    assert meta_ai._extract_json_array(raw) == [{"a": 1}]


def test_extract_json_array_empty():
    assert meta_ai._extract_json_array("") == []
    assert meta_ai._extract_json_array("no array here") == []


def test_run_a1_auto_apply_threshold(isolated, monkeypatch):
    # Stub the LLM: return one auto-tune recommendation
    def fake_run_claude(prompt, timeout=180):
        return json.dumps([{
            "type": "tune",
            "action_class": "auto",
            "title": "Raise slow_tool_p95_ms to 2500",
            "evidence": "19 of 23 flags were noise at 1000ms",
            "confidence": 0.85,
            "target": "slow_tool_p95_ms",
            "new_value": 2500,
        }])
    monkeypatch.setattr(meta_ai, "_run_claude", fake_run_claude)
    # Stub telemetry_query.insights_report so we don't need real telemetry
    monkeypatch.setattr(meta_ai.tq, "insights_report", lambda days: {
        "days": days, "total_calls": 100, "total_errors": 2,
        "overall_error_rate": 0.02, "distinct_tools": 5,
        "usage": [], "dead_tools": [], "slow_tools": [],
        "error_prone_tools": [], "abandoned_queries": [],
    })

    result = meta_ai.run_a1(days=7)
    assert result["created"] == 1
    assert result["auto_applied"] == 1
    # Threshold was actually updated
    assert meta_ai.load_thresholds()["slow_tool_p95_ms"] == 2500


def test_run_a1_downgrades_unsafe_auto_to_queued(isolated, monkeypatch):
    # A1 tries to "auto" a code change — must be downgraded to queued
    def fake_run_claude(prompt, timeout=180):
        return json.dumps([{
            "type": "remove",
            "action_class": "auto",
            "title": "Remove the dirty_repos tool",
            "evidence": "used 0 times in 30 days",
            "confidence": 0.9,
            "target": "",
            "new_value": None,
        }])
    monkeypatch.setattr(meta_ai, "_run_claude", fake_run_claude)
    monkeypatch.setattr(meta_ai.tq, "insights_report", lambda days: {
        "days": days, "total_calls": 10, "total_errors": 0,
        "overall_error_rate": 0.0, "distinct_tools": 1,
        "usage": [], "dead_tools": [], "slow_tools": [],
        "error_prone_tools": [], "abandoned_queries": [],
    })

    result = meta_ai.run_a1(days=7)
    assert result["created"] == 1
    assert result["auto_applied"] == 0
    assert result["items"][0]["action_class"] == "queued"


def test_run_a1_skips_low_confidence(isolated, monkeypatch):
    def fake_run_claude(prompt, timeout=180):
        return json.dumps([
            {"type": "tune", "action_class": "queued", "title": "weak",
             "evidence": "meh", "confidence": 0.3},
            {"type": "tune", "action_class": "queued", "title": "strong",
             "evidence": "clear", "confidence": 0.8},
        ])
    monkeypatch.setattr(meta_ai, "_run_claude", fake_run_claude)
    monkeypatch.setattr(meta_ai.tq, "insights_report", lambda days: {
        "days": days, "total_calls": 1, "total_errors": 0,
        "overall_error_rate": 0.0, "distinct_tools": 0,
        "usage": [], "dead_tools": [], "slow_tools": [],
        "error_prone_tools": [], "abandoned_queries": [],
    })

    result = meta_ai.run_a1(days=7)
    assert result["created"] == 1
    assert result["skipped_low_confidence"] == 1
    assert result["items"][0]["title"] == "strong"


def test_run_a2_writes_pending_proposal(isolated, monkeypatch):
    def fake_run_claude(prompt, timeout=180):
        return json.dumps([{
            "target": "a1_prompt",
            "change_type": "criterion_add",
            "title": "Teach A1 to detect regressions",
            "evidence": "A1 has never flagged a w-over-w p95 growth",
            "confidence": 0.75,
            "diff": "add: flag tools whose p95 grew ≥2x week-over-week",
            "expected_effect": "A1 will emit regression findings",
        }])
    monkeypatch.setattr(meta_ai, "_run_claude", fake_run_claude)
    monkeypatch.setattr(meta_ai.tq, "insights_report", lambda days: {
        "days": days, "total_calls": 0, "total_errors": 0,
        "overall_error_rate": 0.0, "distinct_tools": 0,
        "usage": [], "dead_tools": [], "slow_tools": [],
        "error_prone_tools": [], "abandoned_queries": [],
    })

    result = meta_ai.run_a2(days=7)
    assert result["created"] == 1
    pending = meta_ai.list_proposals(state="pending")
    assert len(pending) == 1
    assert pending[0]["target"] == "a1_prompt"
    assert pending[0]["state"] == "pending"


def test_decide_approve_threshold_change(isolated, monkeypatch):
    # First, manually insert a pending proposal for threshold change
    proposal = {
        "id": "abc123",
        "created_at": meta_ai._now(),
        "agent": "A2",
        "target": "thresholds.json",
        "change_type": "threshold_change",
        "title": "Raise slow threshold to 2500ms",
        "evidence": "rejection pattern",
        "confidence": 0.8,
        "diff": {"key": "slow_tool_p95_ms", "from": 1000, "to": 2500},
        "expected_effect": "fewer slow-tool flags",
        "state": "pending",
        "decided_at": None,
        "decided_reason": None,
        "applied_at": None,
        "apply_error": None,
    }
    meta_ai._append(meta_ai._a2_log(), proposal)

    updated = meta_ai.decide_proposal("abc123", "approved", reason="agree")
    assert updated["state"] == "approved"
    assert updated["apply_error"] is None
    assert meta_ai.load_thresholds()["slow_tool_p95_ms"] == 2500


def test_decide_approve_prompt_edit(isolated):
    new_prompt = "# A1\n\nbrand new prompt body\n"
    proposal = {
        "id": "p2",
        "created_at": meta_ai._now(),
        "agent": "A2",
        "target": "a1_prompt",
        "change_type": "prompt_edit",
        "title": "Rewrite A1 prompt",
        "evidence": "clarity",
        "confidence": 0.9,
        "diff": {"full_new_text": new_prompt},
        "expected_effect": "clearer outputs",
        "state": "pending",
        "decided_at": None,
        "decided_reason": None,
        "applied_at": None,
        "apply_error": None,
    }
    meta_ai._append(meta_ai._a2_log(), proposal)

    updated = meta_ai.decide_proposal("p2", "approved")
    assert updated["state"] == "approved"
    assert updated["apply_error"] is None
    assert meta_ai.A1_PROMPT_FILE.read_text() == new_prompt


def test_decide_reject_does_not_apply(isolated):
    proposal = {
        "id": "p3",
        "created_at": meta_ai._now(),
        "agent": "A2",
        "target": "thresholds.json",
        "change_type": "threshold_change",
        "title": "No",
        "evidence": "bad",
        "confidence": 0.8,
        "diff": {"key": "slow_tool_p95_ms", "from": 1000, "to": 99999},
        "expected_effect": "...",
        "state": "pending",
        "decided_at": None, "decided_reason": None,
        "applied_at": None, "apply_error": None,
    }
    meta_ai._append(meta_ai._a2_log(), proposal)
    meta_ai.decide_proposal("p3", "rejected", reason="too aggressive")
    assert meta_ai.load_thresholds()["slow_tool_p95_ms"] == 1000


def test_decide_unknown_id_raises(isolated):
    with pytest.raises(ValueError):
        meta_ai.decide_proposal("nope", "approved")


def test_decide_invalid_verdict_raises(isolated):
    with pytest.raises(ValueError):
        meta_ai.decide_proposal("any", "maybe")


def test_apply_rejects_non_tunable_key(isolated):
    proposal = {
        "id": "p4",
        "created_at": meta_ai._now(),
        "agent": "A2",
        "target": "thresholds.json",
        "change_type": "threshold_change",
        "title": "Try to set weird key",
        "evidence": "...",
        "confidence": 0.9,
        "diff": {"key": "not_a_real_key", "to": 42},
        "expected_effect": "...",
        "state": "pending",
        "decided_at": None, "decided_reason": None,
        "applied_at": None, "apply_error": None,
    }
    meta_ai._append(meta_ai._a2_log(), proposal)
    updated = meta_ai.decide_proposal("p4", "approved")
    assert updated["state"] == "approved"
    assert "not tunable" in (updated["apply_error"] or "")


def test_event_sourced_state_is_latest(isolated):
    proposal = {
        "id": "p5",
        "created_at": meta_ai._now(),
        "agent": "A2",
        "target": "thresholds.json",
        "change_type": "threshold_change",
        "title": "Something",
        "evidence": "...",
        "confidence": 0.8,
        "diff": {"key": "slow_tool_p95_ms", "to": 1500},
        "expected_effect": "...",
        "state": "pending",
        "decided_at": None, "decided_reason": None,
        "applied_at": None, "apply_error": None,
    }
    meta_ai._append(meta_ai._a2_log(), proposal)
    meta_ai.decide_proposal("p5", "deferred", reason="not now")
    # Latest event wins — state should be deferred, not pending
    pending = meta_ai.list_proposals(state="pending")
    deferred = meta_ai.list_proposals(state="deferred")
    assert not pending
    assert len(deferred) == 1


def test_a1_recent_filters_by_action_class(isolated):
    meta_ai._append(meta_ai._a1_log(), {
        "id": "x1", "created_at": meta_ai._now(),
        "action_class": "auto", "title": "one",
    })
    meta_ai._append(meta_ai._a1_log(), {
        "id": "x2", "created_at": meta_ai._now(),
        "action_class": "queued", "title": "two",
    })
    auto = meta_ai.a1_recent_recommendations(action_class="auto")
    queued = meta_ai.a1_recent_recommendations(action_class="queued")
    assert len(auto) == 1 and auto[0]["title"] == "one"
    assert len(queued) == 1 and queued[0]["title"] == "two"
