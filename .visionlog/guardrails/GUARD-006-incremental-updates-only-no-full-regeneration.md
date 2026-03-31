---
id: "GUARD-006"
type: "guardrail"
title: "Incremental updates only \u2014 no full regeneration"
status: "active"
date: "2026-03-30"
---

Project summaries (L2) and portfolio rollups (L3) must update incrementally when new sessions arrive. Summarize the delta and fold it in. Never regenerate a project summary from all N sessions — that's the same token cost problem as raw merge, just shifted to write time. Full regen is only allowed for repair/correction.
