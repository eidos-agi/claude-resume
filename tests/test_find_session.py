"""Tests for _find_session — resolves Claude-Code, Codex, and Grok sessions.

Regression coverage for:
- Codex rollout-* ids returned by search but unresolvable by _find_session
- Grok 019… ids listed in search but missing from Claude/Codex globs (MS-0002 TASK-0026)
"""

from __future__ import annotations

import json

import pytest

from resume_resume import mcp_server as ms


CLAUDE_UUID = "019ed161-140f-7791-872c-c752174d4a55"
CODEX_ID = "rollout-2026-06-16T12-01-00-019ed161-140f-7791-872c-c752174d4a55"
# Fixture Grok id — same shape as live bug 019f82e1-… (TASK-0026)
GROK_ID = "019f82e1-d2b1-7db1-a82a-77f1f32fd9e6"
EXPECTED_KEYS = {"file", "session_id", "project_dir", "mtime", "size"}


@pytest.fixture
def session_roots(tmp_path, monkeypatch):
    """Mirror the real on-disk layout under a temp dir and point the
    module's PROJECTS_DIR / CODEX_SESSIONS_DIR / GROK_SESSIONS_DIR at it."""
    # Claude: ~/.claude/projects/<encoded>/<uuid>.jsonl
    projects = tmp_path / "projects"
    proj_dir = projects / "-Users-dshanklinbv-repos-eidos-agi-resume-resume"
    proj_dir.mkdir(parents=True)
    claude_file = proj_dir / f"{CLAUDE_UUID}.jsonl"
    claude_file.write_text(
        json.dumps({"type": "user", "message": {"content": "hi"}}) + "\n"
    )

    # Codex: ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl
    codex_root = tmp_path / "codex"
    day_dir = codex_root / "2026" / "06" / "16"
    day_dir.mkdir(parents=True)
    codex_file = day_dir / f"{CODEX_ID}.jsonl"
    codex_file.write_text(
        json.dumps(
            {
                "type": "session_meta",
                "payload": {"cwd": "/Users/dshanklinbv/repos-jetta-operating"},
            }
        )
        + "\n"
    )

    # Grok: ~/.grok/sessions/<url-encoded-cwd>/<id>/chat_history.jsonl
    grok_root = tmp_path / "grok"
    grok_sess = grok_root / "%2FUsers%2Fdshanklinbv%2Frepos-aic%2Fnorthstar" / GROK_ID
    grok_sess.mkdir(parents=True)
    grok_file = grok_sess / "chat_history.jsonl"
    grok_file.write_text(
        json.dumps({"role": "user", "content": "find the northstar chat"}) + "\n"
    )

    monkeypatch.setattr(ms, "PROJECTS_DIR", projects)
    monkeypatch.setattr(ms, "CODEX_SESSIONS_DIR", codex_root)
    monkeypatch.setattr(ms, "GROK_SESSIONS_DIR", grok_root)
    return {"claude": claude_file, "codex": codex_file, "grok": grok_file}


def test_codex_rollout_id_resolves(session_roots):
    result = ms._find_session(CODEX_ID)
    assert result is not None, "Codex rollout id should resolve"
    assert set(result.keys()) == EXPECTED_KEYS
    assert result["file"] == session_roots["codex"]
    assert result["session_id"] == CODEX_ID
    # project_dir derived from the session_meta cwd, matching scan_codex_sessions
    assert result["project_dir"] == "/Users/dshanklinbv/repos-jetta-operating"
    assert result["size"] > 0


def test_normal_uuid_still_resolves(session_roots):
    result = ms._find_session(CLAUDE_UUID)
    assert result is not None, "Claude UUID should still resolve"
    assert set(result.keys()) == EXPECTED_KEYS
    assert result["file"] == session_roots["claude"]
    assert result["session_id"] == CLAUDE_UUID
    assert "resume-resume" in result["project_dir"]


def test_grok_session_id_resolves(session_roots):
    """MS-0002 TASK-0026: Grok ids returned by search must resolve for read_session."""
    result = ms._find_session(GROK_ID)
    assert result is not None, "Grok session id should resolve"
    assert set(result.keys()) == EXPECTED_KEYS
    assert result["file"] == session_roots["grok"]
    assert result["session_id"] == GROK_ID
    assert result["project_dir"] == "/Users/dshanklinbv/repos-aic/northstar"
    assert result["size"] > 0


def test_grok_missing_returns_none(session_roots, monkeypatch, tmp_path):
    empty = tmp_path / "empty-grok"
    empty.mkdir()
    monkeypatch.setattr(ms, "GROK_SESSIONS_DIR", empty)
    # Claude still works; unknown grok-shaped id does not
    assert ms._find_session(CLAUDE_UUID) is not None
    assert ms._find_session("019f9999-0000-7000-8000-000000000001") is None


@pytest.mark.parametrize(
    "bad_id",
    [
        "*",
        "rollout-*",
        "abc?def",
        "id[0-9]",
        "../../etc/passwd",
        "foo/bar",
        "rollout-2026/06/16",
    ],
)
def test_glob_injection_rejected(session_roots, bad_id):
    assert ms._find_session(bad_id) is None
