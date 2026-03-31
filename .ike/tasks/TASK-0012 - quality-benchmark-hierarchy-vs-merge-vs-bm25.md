---
id: TASK-0012
title: Seed query benchmark (30 real queries)
status: To Do
created: '2026-03-30'
priority: high
tags:
  - hierarchy
  - benchmark
dependencies:
  - Backfill projects table from existing chunks
visionlog_goal_id: GOAL-013
updated: '2026-03-30'
---
Capture 30 real queries from actual usage with expected results. For each: the query, expected answer, which sessions contain it, what level should resolve it (L1/L2/L3).

Baseline: run each query against existing RRF search (rrf_search in insights.py) and BM25 (resume-resume search_sessions). Record what works and what fails. This establishes the "before" measurement.

After L2 is built, re-run the same queries. This is the validation loop per SOP-004.
