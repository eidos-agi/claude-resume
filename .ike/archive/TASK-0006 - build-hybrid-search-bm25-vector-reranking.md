---
id: TASK-0006
title: Build hybrid search (BM25 + vector reranking)
status: To Do
created: '2026-03-30'
priority: medium
tags:
  - rag
  - search
dependencies:
  - Embed existing sessions into vector store
visionlog_goal_id: GOAL-013
updated: '2026-03-30'
---
Combine existing BM25 search with vector similarity. Design the fusion strategy (reciprocal rank fusion, weighted scoring, etc.). search_sessions should seamlessly use both signals. Measure quality improvement vs BM25-only on real queries.

**Archived:** Restructured: RAG is deferred, replaced by hierarchical summarization approach
