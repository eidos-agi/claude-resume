---
id: TASK-0016
title: Write-at-land pre-computation — trigger L2 refresh on session end
status: Done
created: '2026-03-31'
priority: High
milestone: MS-0001
tags:
  - architecture
  - daemon
  - write-heavy
dependencies:
  - Wire L2 project summaries into MCP tools
acceptance-criteria:
  - /land triggers daemon L2 refresh; next /takeoff gets instant context
  - Degrades gracefully if daemon is not running (no crash, just stale L2)
  - Queue mechanism uses existing daemon task format
definition-of-done:
  - Bookmark write or session finalization queues L2 refresh to daemon
  - Daemon processes L2 refresh within 60s of queue entry
  - Next /takeoff for that project gets warm L2 without any claude -p call
updated: '2026-04-16'
---
Currently all context is computed at read time (/takeoff). Invert this: when a session ends (/land or bookmark write), trigger L2 summary refresh for that project. The daemon exists and works — use it. Queue an L2 regeneration task to the daemon when a bookmark is written or a session JSONL is finalized. This ensures /takeoff always finds warm L2 content.

**Completion notes:** Cadence task (scheduled-cadence-a1-weekly-a2-bi-weekly) shipped in 6c37624. Scheduling documented in A1+A2 SKILL.md files. The other TASK-0018 (write-at-land L2 refresh) is a separate pre-existing task — YAML fixed but not completed; it remains open.
