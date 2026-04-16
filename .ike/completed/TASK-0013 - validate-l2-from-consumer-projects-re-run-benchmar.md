---
id: TASK-0013
title: Validate L2 from consumer projects + re-run benchmark
status: Done
created: '2026-03-30'
priority: high
tags:
  - hierarchy
  - validation
dependencies:
  - Level 2 — Incremental project summary generator
visionlog_goal_id: GOAL-013
updated: '2026-04-16'
milestone: MS-0001
---
Two-part validation per SOP-004:

1. **Benchmark re-run:** Run the 30 queries from TASK-0012 against L2 summaries. For queries tagged as L2-resolvable, does the project summary answer them without drilling down? Document pass/fail.

2. **Consumer validation:** Cold-start sessions in ciso and director-of-ai. Can the agent read a project summary and be immediately productive? Test: "What's the status of the Wrike renewal?" should be answerable from L2 without searching 5 sessions.

If validation fails, adjust L2 generation before proceeding to L3.

Linked to MS-0001. This is the quality gate — if L2 doesn't pass consumer validation, we fix it before shipping project_orient().

**Completion notes:** Shipped in bd23454. L2 resolves Q16 (Wrike renewal) that BM25 missed entirely. Consumer validation PASS: project_summary answers business questions in <200ms without session drill-down. Recommendation: generate L2 for cockpit-eidos, greenmark-cockpit, reeves.
