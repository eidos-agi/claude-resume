"""MS-0002 / TASK-0025: multi-host session_tool labeling.

Detector lives in resume_resume.session_utils (not claude-session-commons.codex)
so the binary codex|claude helper used by other packages is unchanged.
"""

from pathlib import Path

from resume_resume.session_utils import is_grok_session_id, resume_command, session_tool

CLAUDE_ID = "ddf7fc98-6c93-40c8-9444-503d8a716dbf"
GROK_ID = "019f82e1-d2b1-7db1-a82a-77f1f32fd9e6"
CODEX_ID = "rollout-2026-06-12T08-36-57-019ebc0c-9f4f-7362-9d26-fb071dfeecbe"


def _make_grok_session(root: Path, session_id: str = GROK_ID) -> Path:
    sess = root / "%2FUsers%2Fdemo%2Fproj" / session_id
    sess.mkdir(parents=True)
    (sess / "chat_history.jsonl").write_text('{"role":"user","text":"hi"}\n')
    return sess


def test_session_tool_codex_rollout_prefix():
    assert session_tool(CODEX_ID) == "codex"


def test_session_tool_claude_when_not_under_grok(tmp_path):
    assert session_tool(CLAUDE_ID, grok_root=tmp_path) == "claude"
    # UUID-ish 019… is still claude without a grok directory
    assert session_tool(GROK_ID, grok_root=tmp_path) == "claude"


def test_session_tool_grok_when_directory_exists(tmp_path):
    _make_grok_session(tmp_path)
    empty_claude = tmp_path / "empty-claude-projects"
    empty_claude.mkdir()
    assert (
        session_tool(GROK_ID, grok_root=tmp_path, projects_dir=empty_claude) == "grok"
    )
    assert is_grok_session_id(GROK_ID, grok_root=tmp_path) is True


def test_session_tool_claude_wins_if_both_trees(tmp_path):
    """Pathological dual existence: Claude project path wins over grok dir."""
    _make_grok_session(tmp_path)
    projects = tmp_path / "claude-projects"
    proj = projects / "-Users-demo-northstar"
    proj.mkdir(parents=True)
    (proj / f"{GROK_ID}.jsonl").write_text("{}\n")
    assert session_tool(GROK_ID, grok_root=tmp_path, projects_dir=projects) == "claude"


def test_session_tool_rejects_path_traversal(tmp_path):
    assert session_tool("../evil", grok_root=tmp_path) == "claude"
    assert session_tool("a/b", grok_root=tmp_path) == "claude"
    assert is_grok_session_id("a/b", grok_root=tmp_path) is False


def test_session_tool_empty_id(tmp_path):
    assert session_tool("", grok_root=tmp_path) == "claude"


def test_resume_command_routes_by_host(tmp_path):
    _make_grok_session(tmp_path)
    empty_claude = tmp_path / "empty-claude-projects"
    empty_claude.mkdir()
    assert resume_command(CODEX_ID).startswith("codex resume ")
    assert (
        resume_command(GROK_ID, grok_root=tmp_path, projects_dir=empty_claude)
        == f"grok --resume {GROK_ID}"
    )
    assert resume_command(
        CLAUDE_ID, grok_root=tmp_path, projects_dir=empty_claude
    ).startswith("claude --resume ")


def test_mcp_server_imports_local_session_tool():
    """mcp_server must not re-export the codex-only labeler for host labeling."""
    from resume_resume import mcp_server as ms
    from resume_resume.session_utils import session_tool as local_st

    assert ms.session_tool is local_st
