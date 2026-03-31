---
id: TASK-0014
title: Expose L2/L3 summaries in resume-resume MCP tools
status: To Do
created: '2026-03-30'
priority: medium
tags:
  - hierarchy
  - mcp
  - resume-resume
dependencies:
  - Level 2 — Incremental project summary generator
visionlog_goal_id: GOAL-013
---
Add MCP tools to resume-resume that read from the new summary_levels table in commons:

- `read_project_summary(project_path)` — return L2 summary for a project
- `list_projects(limit, sort_by)` — list projects with session counts and staleness
- `portfolio_view()` — return L3 rollup
- Update `merge_context` to prefer L2 summary over raw session merging when available

These are thin wrappers over commons query functions. The intelligence is in commons; resume-resume just exposes it.
