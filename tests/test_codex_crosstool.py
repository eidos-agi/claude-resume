"""Cross-tool support: Codex messages parse for merge_context, sessions label by tool."""

from resume_resume import mcp_server as ms
from resume_resume.session_utils import session_tool

CODEX_ROLLOUT = (
    '{"timestamp":"2026-06-12T19:00:30Z","type":"session_meta",'
    '"payload":{"id":"019ebc0c-9f4f-7362-9d26-fb071dfeecbe","cwd":"/tmp/demo"}}\n'
    '{"timestamp":"2026-06-12T19:01:00Z","type":"event_msg",'
    '"payload":{"type":"user_message","message":"research the auth token refresh bug"}}\n'
    '{"timestamp":"2026-06-12T19:01:30Z","type":"event_msg",'
    '"payload":{"type":"agent_message","message":"the refresh uses a 24h presigned url"}}\n'
    '{"timestamp":"2026-06-12T19:02:00Z","type":"response_item",'
    '"payload":{"type":"function_call","name":"exec_command","arguments":"{}"}}\n'
)


def test_session_tool_labels_by_source(tmp_path):
    """TASK-0025: rollout→codex; path under grok root→grok; else claude."""
    assert (
        session_tool("rollout-2026-06-12T08-36-57-019ebc0c-9f4f-7362-9d26-fb071dfeecbe")
        == "codex"
    )
    # Claude UUID with no grok dir → claude (do not mislabel as grok by format)
    assert (
        session_tool(
            "ddf7fc98-6c93-40c8-9444-503d8a716dbf",
            grok_root=tmp_path,
        )
        == "claude"
    )
    # Grok: only when the session directory exists under the grok root
    # (and no Claude projects path for that id)
    grok_id = "019f82e1-d2b1-7db1-a82a-77f1f32fd9e6"
    empty_claude = tmp_path / "empty-claude-projects"
    empty_claude.mkdir()
    sess_dir = tmp_path / "%2Ftmp%2Fdemo" / grok_id
    sess_dir.mkdir(parents=True)
    (sess_dir / "chat_history.jsonl").write_text("{}\n")
    assert (
        session_tool(grok_id, grok_root=tmp_path, projects_dir=empty_claude) == "grok"
    )
    # Same id with empty grok root → claude (path is source of truth)
    empty = tmp_path / "empty-grok"
    empty.mkdir()
    assert (
        session_tool(grok_id, grok_root=empty, projects_dir=empty_claude) == "claude"
    )


def test_read_messages_handles_codex_schema(tmp_path):
    f = (
        tmp_path
        / "rollout-2026-06-12T19-00-30-019ebc0c-9f4f-7362-9d26-fb071dfeecbe.jsonl"
    )
    f.write_text(CODEX_ROLLOUT)

    out = ms._read_messages(f, "", 6)
    roles = [m["role"] for m in out["messages"]]
    texts = " ".join(m["text"] for m in out["messages"])

    assert roles == ["user", "assistant"], out
    assert "auth token refresh" in texts
    assert "presigned url" in texts


def test_read_messages_codex_keyword_filter(tmp_path):
    f = tmp_path / "rollout-x-019ebc0c-9f4f-7362-9d26-fb071dfeecbe.jsonl"
    f.write_text(CODEX_ROLLOUT)

    out = ms._read_messages(f, "presigned", 6)
    assert len(out["messages"]) == 1
    assert out["messages"][0]["role"] == "assistant"


# Grok Build chat_history.jsonl shape (TASK-0027 / MS-0002)
GROK_HISTORY = (
    '{"type":"system","content":"You are Grok"}\n'
    '{"type":"user","content":[{"type":"text","text":"do you see the recent claude code chat about northstar?"}]}\n'
    '{"type":"assistant","content":[{"type":"text","text":"I will search resume-resume for the northstar session."}]}\n'
    '{"type":"user","content":"simple string user message about blotter"}\n'
)


def test_read_messages_handles_grok_chat_history(tmp_path):
    """Grok puts content on the entry, not under message (unlike Claude)."""
    f = tmp_path / "chat_history.jsonl"
    f.write_text(GROK_HISTORY)

    out = ms._read_messages(f, "", 10)
    roles = [m["role"] for m in out["messages"]]
    texts = " ".join(m["text"] for m in out["messages"])

    assert "user" in roles and "assistant" in roles
    assert "system" not in roles
    assert "northstar" in texts
    assert "blotter" in texts


def test_read_messages_grok_keyword_filter(tmp_path):
    f = tmp_path / "chat_history.jsonl"
    f.write_text(GROK_HISTORY)

    out = ms._read_messages(f, "blotter", 10)
    assert len(out["messages"]) == 1
    assert out["messages"][0]["role"] == "user"
    assert "blotter" in out["messages"][0]["text"]
