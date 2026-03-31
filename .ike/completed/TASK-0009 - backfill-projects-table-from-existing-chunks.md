---
id: TASK-0009
title: Backfill projects table from existing chunks
status: Done
created: '2026-03-30'
priority: high
tags:
  - hierarchy
  - backfill
  - commons
dependencies:
  - Add projects + summary_levels tables to insights.db
visionlog_goal_id: GOAL-013
updated: '2026-03-30'
---
project_path already exists on every chunk — detection is solved. This task is just aggregation:

1. Query `SELECT DISTINCT project_path, COUNT(DISTINCT session_id), MAX(timestamp) FROM chunks GROUP BY project_path`
2. Insert into projects table
3. Add a trigger or daemon hook so new sessions auto-register their project
4. Derive project name from path (last directory component or repo name)

No ML, no keyword matching, no tagging model. The data is already there.
