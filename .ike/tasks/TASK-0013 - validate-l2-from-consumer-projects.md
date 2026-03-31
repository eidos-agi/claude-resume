---
id: TASK-0013
title: Validate L2 from consumer projects + re-run benchmark
status: To Do
created: '2026-03-30'
priority: high
tags:
  - hierarchy
  - validation
dependencies:
  - Level 2 — Incremental project summary generator
visionlog_goal_id: GOAL-013
updated: '2026-03-30'
---
Two-part validation per SOP-004:

1. **Benchmark re-run:** Run the 30 queries from TASK-0012 against L2 summaries. For queries tagged as L2-resolvable, does the project summary answer them without drilling down? Document pass/fail.

2. **Consumer validation:** Cold-start sessions in ciso and director-of-ai. Can the agent read a project summary and be immediately productive? Test: "What's the status of the Wrike renewal?" should be answerable from L2 without searching 5 sessions.

If validation fails, adjust L2 generation before proceeding to L3.
