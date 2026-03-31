---
title: "resume-resume: Hierarchical Memory for AI Agents"
type: "vision"
date: "2026-03-30"
---

resume-resume is a session persistence and retrieval layer for Claude Code, built on claude-session-commons.

Commons already provides: session discovery, JSONL parsing, turn/subagent chunking, 384-dim embeddings (BAAI/bge-small-en-v1.5 via fastembed), SQLite + sqlite-vec vector storage, RRF hybrid search (semantic + FTS5 + entity), a background daemon (5-min polling), and L1 session summaries via `claude -p`. ~4,000 lines, well-tested.

What's missing: project-level grouping and hierarchical summaries. `project_path` exists as a flat string on every chunk but nothing aggregates by it. The next step is adding a projects table + summary_levels table to insights.db, building an incremental L2 summarizer that folds session summaries into project narratives, and wiring it into the existing daemon.

The hierarchy:
- Level 0: Raw messages (existing — JSONL files)
- Level 1: Session summaries (existing — summarize_quick + summarize_deep)
- Level 2: Project summaries (TO BUILD — aggregate L1 by project_path)
- Level 3: Portfolio rollups (TO BUILD — aggregate L2 across projects)

resume-resume exposes this via MCP tools. Commons owns the data + compression engine.
