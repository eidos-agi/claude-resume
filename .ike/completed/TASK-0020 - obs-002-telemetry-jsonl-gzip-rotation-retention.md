---
id: TASK-0020
title: 'obs-002: telemetry JSONL gzip rotation + retention'
status: Done
created: '2026-04-15'
priority: low
tags:
  - observability
  - known-issues
updated: '2026-04-16'
---
Telemetry files grow unbounded. Gzip files older than 7 days. Optional RESUME_RESUME_TELEMETRY_RETENTION_DAYS env var. See docs/known-issues.md obs-002.

**Completion notes:** Shipped in 6c37624. Gzip after 7 days, retention via env var, reader handles .jsonl.gz transparently. 3 rotation tests.
