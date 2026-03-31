---
id: "GUARD-002"
type: "guardrail"
title: "No direct Anthropic API calls"
status: "active"
date: "2026-03-30"
---

All LLM operations (summarization, synthesis, classification) must use `claude -p`, never the Anthropic SDK directly. If `claude -p` fails or times out, debug it — do not fall back to API. This is an org-wide hard constraint.
