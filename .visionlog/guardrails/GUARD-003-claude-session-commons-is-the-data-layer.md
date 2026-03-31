---
id: "GUARD-003"
type: "guardrail"
title: "Build on existing commons infrastructure \u2014 no parallel systems"
status: "active"
date: "2026-03-30"
---

Commons already has SQLite + sqlite-vec (insights.db), fastembed (BAAI/bge-small-en-v1.5), a daemon, and RRF search. Do not introduce a second database, a different embedding model, or a competing indexing pipeline. Extend insights.db with new tables (projects, summary_levels). Use the existing daemon for scheduling. Use the existing summarize.py pattern (claude -p) for L2/L3 generation.
