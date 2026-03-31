---
id: "SOP-004"
type: "sop"
title: "Build-Validate-Adjust Loop"
status: "draft"
date: "2026-03-30"
---

Every new hierarchy level follows this loop before proceeding to the next:

1. **Research** — Run research.md for any consequential design decision (schema, chunking strategy, summarization approach). Earn the decision with evidence before building.

2. **Build** — Implement the level. Ship working code, not a prototype.

3. **Validate with real queries** — Test against the query benchmark (TASK-0012 seeds it, but validation happens after EACH level, not just at the end). Use 10+ real queries from actual session history. Measure: did the summary answer the question? Did the user need to drill down?

4. **Validate with consumers** — Test from the consuming projects (ciso, director-of-ai, etc.). Can a cold-start session in ciso read a project summary and be immediately useful? If not, the summary format or content is wrong.

5. **Adjust or proceed** — If validation reveals gaps, fix them before moving to the next level. If a level doesn't add value, stop — don't build upward on a shaky foundation.

The loop is: research → build → validate (queries) → validate (consumers) → adjust → next level.
