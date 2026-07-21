"""Golden regression for MS-0002 multi-host search seams.

Failure mode (2026-07-21): agent asked for recent Claude Code chat about
northstar. Real session on disk:

  ~/.claude/projects/...-northstar/727d811c-41f7-42f7-b517-ba4c525baf4e.jsonl
  (cwd ~/repos-aic/northstar — Chapter 4 held pending trade blotter)

Symptoms:
  1. Grok hot IDs (019f…) labeled tool=claude via codex.session_tool
  2. Those IDs returned by search but _find_session / read_session → not found
  3. Hot recency drowned cold northstar summary hit

These tests use fixtures only — no live ~/.grok or Daniel machine state.
Anchor session id in docstrings: 727d811c-41f7-42f7-b517-ba4c525baf4e
"""

from __future__ import annotations

import json
from pathlib import Path

from resume_resume import mcp_server as ms
from resume_resume.session_utils import session_tool

# Anchor from 2026-07-21 northstar failure
NORTHSTAR_CLAUDE_ID = "727d811c-41f7-42f7-b517-ba4c525baf4e"
GROK_HOT_ID = "019f82e1-d2b1-7db1-a82a-77f1f32fd9e6"
CODEX_ID = "rollout-2026-06-12T08-36-57-019ebc0c-9f4f-7362-9d26-fb071dfeecbe"


def test_session_tool_labels_three_hosts(tmp_path):
    """TASK-0025: rollout→codex; grok path→grok; else claude."""
    empty_claude = tmp_path / "empty-claude-projects"
    empty_claude.mkdir()
    assert session_tool(CODEX_ID) == "codex"
    assert (
        session_tool(
            NORTHSTAR_CLAUDE_ID, grok_root=tmp_path, projects_dir=empty_claude
        )
        == "claude"
    )
    sess = tmp_path / "%2FUsers%2Fdemo%2Fnorthstar" / GROK_HOT_ID
    sess.mkdir(parents=True)
    (sess / "chat_history.jsonl").write_text("{}\n")
    assert (
        session_tool(GROK_HOT_ID, grok_root=tmp_path, projects_dir=empty_claude)
        == "grok"
    )


def test_find_and_read_all_three_hosts(tmp_path, monkeypatch):
    """TASK-0026+0027: every resolvable host id is openable by read path."""
    # Claude
    projects = tmp_path / "projects"
    claude_dir = projects / "-Users-dshanklinbv-repos-aic-northstar"
    claude_dir.mkdir(parents=True)
    claude_file = claude_dir / f"{NORTHSTAR_CLAUDE_ID}.jsonl"
    claude_file.write_text(
        json.dumps(
            {
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "text",
                            "text": "GATE C: HOLD chapter 4 until trade blotter",
                        }
                    ]
                },
            }
        )
        + "\n"
        + json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "text", "text": "Standing down. Chapter held."}]
                },
            }
        )
        + "\n"
    )

    # Codex
    codex_root = tmp_path / "codex" / "2026" / "06" / "12"
    codex_root.mkdir(parents=True)
    codex_file = codex_root / f"{CODEX_ID}.jsonl"
    codex_file.write_text(
        '{"type":"session_meta","payload":{"cwd":"/tmp/demo"}}\n'
        '{"type":"event_msg","payload":{"type":"user_message","message":"codex user"}}\n'
        '{"type":"event_msg","payload":{"type":"agent_message","message":"codex assistant"}}\n'
    )

    # Grok
    grok_root = tmp_path / "grok"
    grok_sess = grok_root / "%2Ftmp%2Fdemo" / GROK_HOT_ID
    grok_sess.mkdir(parents=True)
    grok_file = grok_sess / "chat_history.jsonl"
    grok_file.write_text(
        json.dumps(
            {
                "type": "user",
                "content": [
                    {"type": "text", "text": "do you see the recent claude chat about northstar?"}
                ],
            }
        )
        + "\n"
        + json.dumps(
            {
                "type": "assistant",
                "content": [{"type": "text", "text": "searching resume-resume"}],
            }
        )
        + "\n"
    )

    monkeypatch.setattr(ms, "PROJECTS_DIR", projects)
    monkeypatch.setattr(ms, "CODEX_SESSIONS_DIR", tmp_path / "codex")
    monkeypatch.setattr(ms, "GROK_SESSIONS_DIR", grok_root)

    for sid, needle in (
        (NORTHSTAR_CLAUDE_ID, "blotter"),
        (CODEX_ID, "codex user"),
        (GROK_HOT_ID, "northstar"),
    ):
        found = ms._find_session(sid)
        assert found is not None, f"{sid} must resolve"
        out = ms._read_messages(found["file"], "", 10)
        assert out["total"] >= 1, f"{sid} must yield messages"
        blob = " ".join(m["text"] for m in out["messages"])
        assert needle in blob, f"{sid} messages should contain {needle!r}"


def test_project_dir_resolve_for_northstar_anchor(tmp_path, monkeypatch):
    """TASK-0029: empty summary project_dir filled from filesystem layout."""
    from resume_resume import search_index as si

    projects = tmp_path / "projects"
    proj = projects / "-Users-dshanklinbv-repos-aic-northstar"
    proj.mkdir(parents=True)
    (proj / f"{NORTHSTAR_CLAUDE_ID}.jsonl").write_text("{}\n")

    monkeypatch.setattr(
        "claude_session_commons.discovery.PROJECTS_DIR",
        projects,
        raising=False,
    )
    # Direct resolve via our helper with patched PROJECTS_DIR import path
    monkeypatch.setattr(si, "_session_meta", lambda sid: {})

    summary = {
        "summary": {
            "title": "Chapter 4 case study held pending trade blotter evidence",
            "objective": "northstar shelf case study",
            "state": "HELD",
            # deliberately no project_dir
        }
    }
    path = tmp_path / f"{NORTHSTAR_CLAUDE_ID}.json"
    path.write_text(json.dumps(summary))

    # Force _resolve_project_dir to see our projects tree
    def fake_resolve(sid):
        if sid == NORTHSTAR_CLAUDE_ID:
            matches = list(projects.glob(f"*/{sid}.jsonl"))
            if matches:
                from claude_session_commons import decode_project_path

                return decode_project_path(matches[0].parent.name)
        return ""

    monkeypatch.setattr(si, "_resolve_project_dir", fake_resolve)
    parsed = si._parse_summary_file(path)
    assert parsed is not None
    assert "northstar" in (parsed.get("project_dir") or "").lower()
