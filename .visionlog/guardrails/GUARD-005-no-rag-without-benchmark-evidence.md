---
id: "GUARD-005"
type: "guardrail"
title: "No RAG without benchmark evidence"
status: "active"
date: "2026-03-30"
---

GOAL-014 (RAG Pipeline) must not be started until TASK-0012 (quality benchmark) is complete and demonstrates specific retrieval failures that hierarchical summaries + BM25 cannot solve. "It might be better" is not evidence. Show the queries that fail.
