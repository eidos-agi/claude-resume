---
id: TASK-0005
title: Embed existing sessions into vector store
status: To Do
created: '2026-03-30'
priority: medium
tags:
  - rag
  - embeddings
dependencies:
  - 'Research: RAG architecture for session retrieval'
visionlog_goal_id: GOAL-013
updated: '2026-03-30'
---
After architecture decision: chunk sessions (summaries + key messages), generate embeddings, store in chosen vector DB. Design chunking strategy — session-level vs passage-level. Build the ingest pipeline that runs on new sessions automatically.

**Archived:** Restructured: RAG is deferred, replaced by hierarchical summarization approach
