# claude-resume

**Your Mac crashed. Your Claude Code sessions didn't.**

A terminal UI that finds your recently active Claude Code sessions, tells you what each one was doing, and gets you back to work with one keypress.

## The Problem

Your Mac kernel panics mid-session. You reboot. You had three Claude Code sessions open across different projects. Which ones? What were they doing? Where did they leave off?

Claude Code stores session data in `~/.claude/projects/` as JSONL files, but good luck browsing thousands of sessions to find the three that matter.

## What This Does

Launches instantly. Shows your recent sessions grouped by time. Each one gets an AI-generated summary of what you were working on, where you left off, and which files matter. Arrow to the one you want, hit Enter, and the resume command is on your clipboard.

```
┌─ claude-resume ─────────────────────┬──────────────────────────────────────┐
│ ── Today ──                         │ Fix auth token refresh bug           │
│ ❱ Fix auth token refresh bug        │                                      │
│   ~/repos/myapp  12 minutes ago     │ Directory:   ~/repos/myapp           │
│                                     │ Last active: 12 minutes ago          │
│   Add dark mode to settings page    │ Size:        4.2 MB                  │
│   ~/repos/frontend  2 hours ago     │                                      │
│                                     │ Session stats:                       │
│ ── Yesterday ──                     │   Duration:     1h 23m               │
│   Refactor database migrations      │   User msgs:    47                   │
│   ~/repos/backend  18 hours ago     │   Tool uses:    312                  │
│                                     │                                      │
│                                     │ Goal:                                │
│                                     │ Fix the auth token refresh that was  │
│                                     │ silently failing after 401 responses │
│                                     │ from the /api/user endpoint.         │
│                                     │                                      │
│                                     │ Where you left off:                  │
│                                     │ Mid-edit in auth/refresh.ts. The     │
│                                     │ retry logic was added but the test   │
│                                     │ for expired tokens was still failing │
│                                     │ with a race condition.               │
│                                     │                                      │
│                                     │ Key files:                           │
│                                     │   • src/auth/refresh.ts              │
│                                     │   • tests/auth.test.ts               │
│                                     │   • src/api/client.ts                │
└─────────────────────────────────────┴──────────────────────────────────────┘
```

## Install

```bash
git clone https://github.com/rhea-impact/claude-resume
cd claude-resume
pip install -e .
```

This puts `claude-resume` on your PATH immediately. Since it's an editable install (`-e`), pulling updates from the repo takes effect without reinstalling.

Requires Python 3.11+ and [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (uses `claude -p` for summaries).

## Usage

```bash
claude-resume            # Sessions from last 4 hours
claude-resume 24         # Last 24 hours
claude-resume --all      # Everything
claude-resume --cache-all  # Pre-index all sessions (background, slow)
```

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `↑` `↓` | Navigate sessions |
| `r` | Resume directly — exec into the session, no clipboard |
| `Enter` | Copy resume command to clipboard |
| `Space` | Select/deselect for multi-resume |
| `x` | Export context briefing as markdown to clipboard |
| `→` `←` | Scroll preview pane |
| `/` | Search across all session content |
| `d` | Toggle `--dangerously-skip-permissions` |
| `D` | Deep dive — longer, more detailed summary |
| `p` | Patterns — analyze your prompting habits |
| `b` | Toggle automated/bot sessions |
| `Esc` | Quit |

## Session Bookmarks

By default, claude-resume infers session state from AI summaries — it guesses whether you finished, crashed, or got stuck. Bookmarks replace guessing with ground truth.

Run `/bookmark` inside any Claude Code session before you close it. It captures:

- **Lifecycle state** — done, paused, blocked, or handing off
- **Next actions** — what you (or the next person) should do first
- **Blockers** — what's preventing progress
- **Confidence** — how stable the current state is
- **Workspace snapshot** — git status, uncommitted files, current branch

Bookmarked sessions show a colored badge in the TUI list:

| Badge | Meaning |
|-------|---------|
| `DONE` (green) | Work is complete |
| `PAUSED` (yellow) | Intentional stop, will return |
| `BLOCKED` (red) | Can't proceed, external dependency |
| `HANDOFF` (cyan) | Someone else is taking over |
| `AUTO` (dim) | Session closed without explicit bookmark |

The preview pane shows bookmark data — next actions, blockers, confidence — below the AI summary. The `x` export includes it in the markdown briefing.

Sessions without bookmarks work exactly as before (AI-inferred state). Bookmarks are additive — they enrich, they don't replace.

### How bookmarks get created

1. **`/bookmark`** — You type this in Claude Code. It asks which state, captures context in <30 seconds.
2. **`/bookmark done`** — Skip the prompt, go straight to a specific state (`done`, `pause`, `blocked`, `handoff`).
3. **Auto-bookmark** — A `Stop` hook captures minimal workspace state when you close a session without bookmarking. Better than nothing.

### How bookmarks affect sorting

Bookmarked sessions get lifecycle-aware interruption scores:

- `done` → score 0 (no urgency, sorts to bottom)
- `blocked` → score 70 (needs attention, sorts high)
- `paused` → minimum score 20 (low urgency)
- `auto-closed` → normal heuristic scoring

### Setup

The `/bookmark` skill lives at `~/.claude/skills/bookmark/SKILL.md`. The auto-bookmark hook lives at `~/.claude/hooks/session_bookmark_auto.sh`. Both are installed alongside this repo — see the [install instructions](#install).

Bookmark data is stored in the same `~/.claude/resume-summaries/` cache that claude-resume already reads from (as a `bookmark` field in each session's JSON). A backup goes to devlog for cross-machine durability.

## How It Works

1. Scans `~/.claude/projects/` for JSONL session files
2. Scores each by interruption severity — sessions that crashed mid-tool-use go first, bookmarked sessions use lifecycle-aware scoring
3. Summarizes each via `claude -p` (Haiku for speed, cached after first run)
4. Classifies sessions as interactive or automated using a trained ML model — automated sessions (CI, scripts, subagents) are hidden by default
5. Surfaces bookmark data (lifecycle badges, next actions, blockers) when present
6. Presents everything in a [Textual](https://textual.textualize.io/) TUI

Summaries are cached in `~/.claude/resume-summaries/`. Second launch is instant.

## The Classifier

Sessions from scripts, CI pipelines, and subagents clutter the list. A gradient boosting model (trained on ~3,800 sessions) separates human sessions from automated ones using signals like typing pace, casualness, typos, and message patterns. Uncertain cases get escalated to Opus for a second opinion via `--cache-all`.

You probably don't need to retrain it. But if you want to:

```bash
pip install -e ".[train]"
python train_classifier.py
```

## Roadmap

All five launch features are implemented:

- [x] [**Resume directly**](https://github.com/rhea-impact/claude-resume/issues/1) — `r` to exec into a session
- [x] [**Multi-select workspace recovery**](https://github.com/rhea-impact/claude-resume/issues/2) — Space to select, Enter/r to open all in iTerm tabs
- [x] [**Smart sort by interruption**](https://github.com/rhea-impact/claude-resume/issues/3) — sessions scored by how interrupted they look
- [x] [**Export context briefing**](https://github.com/rhea-impact/claude-resume/issues/4) — `x` to copy markdown briefing to clipboard
- [x] **Session bookmarks** — `/bookmark` in Claude Code to capture lifecycle state, displayed as badges in the TUI

## License

MIT
