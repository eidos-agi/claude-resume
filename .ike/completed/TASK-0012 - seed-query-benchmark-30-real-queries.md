---
id: TASK-0012
title: Seed query benchmark (30 real queries)
status: Done
created: '2026-03-30'
priority: high
tags:
  - hierarchy
  - benchmark
dependencies:
  - Backfill projects table from existing chunks
visionlog_goal_id: GOAL-013
updated: '2026-04-16'
milestone: MS-0001
---
Capture 30 real queries from actual usage with expected results. For each: the query, expected answer, which sessions contain it, what level should resolve it (L1/L2/L3).

Baseline: run each query against existing RRF search (rrf_search in insights.py) and BM25 (resume-resume search_sessions). Record what works and what fails. This establishes the "before" measurement.

After L2 is built, re-run the same queries. This is the validation loop per SOP-004.

Linked to MS-0001 (Instant Project Context). This benchmark validates whether L2 summaries actually answer the questions users ask. Without it we're shipping blind.

**Completion notes:** Shipped in 4565343. 30 queries across 6 categories. Baseline: 23 HIT / 3 WEAK / 2 MISS. Gaps: temporal queries (unsupported), business-context queries (need L2), generic dev terms (low IDF noise).
