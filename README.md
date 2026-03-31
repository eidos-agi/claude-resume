<p align="center">
  <img src="https://raw.githubusercontent.com/eidos-agi/resume-resume/master/assets/logo.png" alt="resume-resume" width="480"/>
</p>

# resume-resume

**New free tool we're dropping.**

| | |
|---|---|
| | |
| **Resume** | Find old programming sessions in plain English and pick up where you left off. |
| **Dirty Repos** | See every repo with uncommitted changes across your entire machine — your standing to-do list. Scored by file count and recency. |
| **Crash Recovery** | `boot_up` finds interrupted sessions AND scans all repos for dirty git state. Ready-to-paste resume commands. |
| **Prioritize** | Auto-ranks sessions and repos by urgency — dirty files don't age out, recent active work surfaces first. |
| **Speed** | Parallelized BM25 search across gigabytes of past chats in seconds. Parallel git status scans across 50+ repos. |
| **Cost Savings** | Uses Haiku to summarize past context once, then caches permanently — searching thousands of sessions costs nothing after first run. |
| **Merge** | Merge multiple old chats together, pulling context across sessions into a single conversation. |

---

## MCP Server

Add it to Claude Code and every session on your machine can search, read, and merge your full session history — in plain English.

```bash
pip install resume-resume
claude mcp add resume-resume -- resume-resume-mcp
```

Or manually in your MCP config:

```json
{
  "mcpServers": {
    "resume-resume": {
      "command": "resume-resume-mcp"
    }
  }
}
```

We built **Eidos**, a multi-agent AI system. In [our benchmark](https://github.com/eidos-agi/cockpit-eidos), Eidos outperformed **Claude Opus 4.6** by **3.6x** in both accuracy and speed on complex tasks with 15+ reasoning chains. Below, we use Claude Resume to pick up where we left off across multiple sessions.

### Finding the benchmark where Eidos beat Claude Opus 4.6

> *"use resume-resume to find the eidos test where we beat claude"*

![resume-resume eidos benchmark search](https://raw.githubusercontent.com/eidos-agi/resume-resume/master/assets/example-eidos-beat.png)

### Searching for a past session in plain English

> *"use resume-resume to find the latest chats about eidos philosophy docs"*

![resume-resume search example](https://raw.githubusercontent.com/eidos-agi/resume-resume/master/assets/example-search.png)

### Merging multiple past sessions into this chat

> *"use claude resume to merge march 14th conversations and Eidos v5 Pipeline Telemetry convo from march 11th into this chat"*

![resume-resume merge example](https://raw.githubusercontent.com/eidos-agi/resume-resume/master/assets/example-merge.png)

Two sessions — one about eidos-philosophy doc changes (Mar 14) and one with a full 28-task strategic plan (Mar 11) — merged into the current conversation with a single command.

### MCP Tools

| Tool | What it does |
|------|-------------|
| `boot_up(hours)` | Crash recovery — finds interrupted sessions + scans all repos for dirty git state. Scores by urgency (session recency + dirty file count + dirty file recency). Includes ready-to-paste `resume_cmd` for each result. |
| `dirty_repos()` | Standing inventory of every repo with uncommitted changes. No time window — only shrinks by committing. Sorted by urgency score. |
| `search_sessions(query)` | Full-text search across 5,000+ sessions in ~3s, ranked by BM25 |
| `recent_sessions(hours)` | List recently active sessions |
| `read_session(id, keyword)` | Read actual messages from a session, with optional keyword filter |
| `session_summary(id)` | AI summary — cached instantly, generated in ~15s if not |
| `merge_context(id, mode)` | Import context from another session (`summary`, `messages`, or `hybrid`) |
| `session_timeline(id)` | Structured milestone timeline — file edits, commits, instructions |
| `session_thread(id)` | Follow continuation links across a multi-session thread |
| `resume_in_terminal(id)` | Open a session in a new terminal window (iTerm2 or Terminal.app) |
| `session_insights(section)` | Deep analytics across all sessions — patterns, personality, predictions |
| `session_xray(id)` | Single-session breakdown — duration, tokens, tool counts, branches |

---

## Quick Resume — Paste & Go

`claude --resume <id>` fails if you're in the wrong directory. `cr` fixes that — paste any claude command and it auto-discovers the correct project directory, ensures the right flags are on, and launches.

```bash
cr claude --resume ddf7fc98-6c93-40c8-9444-503d8a716dbf
cr claude --resume ddf7fc98-6c93-40c8-9444-503d8a716dbf --model opus --chrome
cr ddf7fc98-6c93-40c8-9444-503d8a716dbf
```

What it does:
1. Parses the session ID out of whatever you pasted
2. Searches `~/.claude/projects/*/` to find which project owns that session
3. Resolves the encoded directory name back to a real filesystem path
4. Adds `--dangerously-skip-permissions` and `--enable-auto-mode` if not already present
5. Pops a macOS dialog showing the session, resolved cwd, and full command (proof it worked — visible outside the TUI)
6. `cd`s to the correct directory and `exec`s into Claude

No more "No conversation found" errors from being in the wrong folder.

---

## TUI

For when your machine died and you just need to get back to work.

```bash
pip install resume-resume
resume-resume        # last 4 hours
cr 24                # last 24 hours
cr --all             # everything
```

![resume-resume TUI](https://raw.githubusercontent.com/eidos-agi/resume-resume/master/assets/tui.png)

| Key | Action |
|-----|--------|
| `↑` `↓` | Navigate sessions |
| `r` | Resume directly — exec into the session |
| `Enter` | Copy resume command to clipboard |
| `Space` | Select for multi-resume (opens all in iTerm tabs) |
| `x` | Export context briefing as markdown |
| `/` | Search across all session content |
| `D` | Deep dive summary |
| `p` | Analyze prompting patterns |
| `b` | Toggle automated/bot sessions |

Requires Python 3.11+ and [Claude Code](https://docs.anthropic.com/en/docs/claude-code).

---

## How It Works

1. Scans `~/.claude/projects/` for JSONL session files
2. Scans all project directories for dirty git state (parallel `git status --porcelain`)
3. Scores sessions by urgency: session recency (2h half-life) + repo dirty urgency (file count + dirty file recency)
4. Dirty repos bypass age filters — uncommitted work doesn't age out
5. Summarizes via `claude -p` with Haiku, cached permanently after first run
6. Classifies sessions as human or automated using a gradient boosting model trained on 3,800 sessions — bot sessions hidden by default
7. Surfaces bookmark data (lifecycle badges, next actions, blockers) when present
8. Reports negative space — how many repos were scanned, how many were clean vs dirty

Run `/bookmark` inside any Claude Code session to capture lifecycle state (`done`, `paused`, `blocked`, `handoff`) before closing. An auto-bookmark Stop hook captures minimal state when you don't.

---

## Related

- [claude-session-commons](https://github.com/eidos-agi/claude-session-commons) — Shared session parsing, caching, and classification used by this repo and others
- [resume-resume-duet](https://github.com/eidos-agi/resume-resume-duet) — Web UI companion with session browser and `resume-resume://` URL scheme handler

## License

MIT
