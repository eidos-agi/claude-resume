---
id: TASK-0010
title: Level 2 — Incremental project summary generator
status: Done
created: '2026-03-30'
priority: high
tags:
  - hierarchy
  - synthesis
dependencies:
  - Seed query benchmark (30 real queries)
visionlog_goal_id: GOAL-013
updated: '2026-03-30'
---
Follow the existing summarize.py pattern (claude -p with structured JSON output).

**Initial generation:** For a project, gather all L1 session summaries (summary_quick from cache). Feed to claude -p with a prompt: "Synthesize these N session summaries into a project narrative. Include: key decisions, current status, open threads, blockers." Cap input at ~8k tokens (truncate oldest sessions). Store in summary_levels.

**Incremental update:** When daemon detects new sessions for a project, feed the existing L2 summary + new session summaries to claude -p: "Update this project summary with these new sessions. Fold in new information, drop stale details." Store updated summary, track source_ids for audit.

**Wire into daemon.py:** Add a post-indexing hook. After indexing a session, check if its project's L2 summary is stale (new sessions since last L2 generation). If stale, queue L2 regeneration. Respect GUARD-006 (incremental, not full regen).

**Output format:** Compatible with director-of-ai/projects/ structure per GUARD-004.
