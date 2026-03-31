---
id: TASK-0011
title: Level 3 — Portfolio rollups
status: To Do
created: '2026-03-30'
priority: medium
tags:
  - hierarchy
  - portfolio
dependencies:
  - Validate L2 from consumer projects + re-run benchmark
visionlog_goal_id: GOAL-013
updated: '2026-03-30'
---
Same pattern as L2, one level up. Feed L2 project summaries to claude -p: "Summarize active projects across this portfolio. What's moving, what's stalled, what needs attention?"

Trigger: daily or on-demand. Store in summary_levels with level=3. This powers cross-project views like "what did I work on this week?" and cockpit dashboards.

Only build after L2 validation passes (TASK-0013).
