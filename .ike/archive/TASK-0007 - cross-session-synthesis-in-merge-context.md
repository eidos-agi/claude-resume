---
id: TASK-0007
title: Cross-session synthesis in merge_context
status: To Do
created: '2026-03-30'
priority: medium
tags:
  - rag
  - synthesis
dependencies:
  - Build hybrid search (BM25 + vector reranking)
visionlog_goal_id: GOAL-013
updated: '2026-03-30'
---
Upgrade merge_context to support pulling from multiple sessions and synthesizing a unified context — not just concatenating raw imports. When merging 5 sessions about "Wrike renewal", produce a coherent narrative, not 5 separate dumps.

**Archived:** Restructured: RAG is deferred, replaced by hierarchical summarization approach
