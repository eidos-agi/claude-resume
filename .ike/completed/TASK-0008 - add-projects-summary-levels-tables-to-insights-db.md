---
id: TASK-0008
title: Add projects + summary_levels tables to insights.db
status: Done
created: '2026-03-30'
priority: high
tags:
  - hierarchy
  - schema
  - commons
visionlog_goal_id: GOAL-013
updated: '2026-03-30'
---
No research gate needed — commons already chose SQLite + sqlite-vec + fastembed. The schema decision is scoped: add two tables to the existing insights.db.

**projects table:** Aggregate sessions by project_path (already exists on every chunk). Columns: id, path (unique), name, summary, metadata (JSON), last_activity, session_count, indexed_at.

**summary_levels table:** Store hierarchical summaries. Columns: id, level (1=session, 2=project, 3=portfolio), entity_id (session_id or project path), entity_type, title, summary_text, source_ids (JSON array of child summary IDs for incremental tracking), created_at, updated_at.

Populate projects table from existing chunks: `SELECT DISTINCT project_path FROM chunks`. Wire into init_db() in insights.py. Add migration path for existing databases.
