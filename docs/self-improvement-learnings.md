# What We Learned About AI Self-Improvement

Lessons from a single session: 43 commits, 112 tests, v0.4.1, starting
from "does resume-resume keep a log of MCP traffic?" and ending with a
fully instrumented self-observation pyramid + measurable product improvements.

---

## 1. The meta-stack's value is as a forcing function, not an oracle

A1's first recommendation was "dirty_repos is slow" — visible from the
first `self_insights` call with human eyes. A2's first proposal was
"codify a rule A1 already followed correctly." Neither AI layer produced
a non-obvious insight.

**But building the stack forced systematic observation.** Without
telemetry, I wouldn't have looked at latency numbers. Without A1, I
wouldn't have structured the observation into actionable categories.
Without A2, I wouldn't have noticed the observation methodology had
gaps. The value is in the structure, not the recommendations.

**Implication:** at low volume, the pyramid produces meta-activity more
than product progress. This was anticipated (ADR-002) and confirmed.
The stack's value will compound as telemetry accumulates — but early
on, just reading the raw numbers is more actionable than the AI on top.

## 2. Your observability system will observe itself — and break

The first three production bugs the telemetry surfaced were IN the
telemetry system:

- **obs-003:** self_* tools averaged 95 SECONDS because the middleware
  logged full results, which contained prior full results, which
  contained prior full results... O(n^2) recursive bloat. The single
  worst bug this session produced — and it was in the observation
  layer itself.
- **obs-004:** test runs generated fake telemetry (83% error rate on
  self_process_decide was entirely test noise). The observation system
  couldn't distinguish its own tests from production.
- **13.3 GB file:** one day of recursive-bloat telemetry consumed more
  disk than most databases.

**Implication:** the first thing to monitor in any monitoring system is
the monitoring system. Ship result-size caps and test isolation on day
one, not after you discover 95-second tool calls.

## 3. Measure before you claim improvement

The 30-query search benchmark was the single most productive deliverable
of the session. Before it: "search seems okay." After it: "23 HIT / 3
WEAK / 2 MISS, with specific queries and scores."

Every subsequent search improvement (domain stop words, temporal filter,
L2 fallback, project filter) was validated against the benchmark. The
benchmark turned opinions into facts:
- Q15 "git rebase merge conflict": 27.1 → 30.0 (WEAK → HIT)
- Q16 "Wrike renewal": 0.0 → 100.0 (MISS → HIT via L2 fallback)
- Q27 "what was I working on yesterday": 0.0 → addressable via `hours`

**Implication:** build the benchmark BEFORE you start improving. The
"before" measurement is the most important one — without it, you can't
prove anything got better.

## 4. Fix the real thing, not the thing that observes it

The first half of the session built observation infrastructure (telemetry,
A1/A2 skills, meta-AI data layer). The second half fixed actual product
bugs. The user asked: "is this moving toward a better tool yet?" Honest
answer at that point: no.

The turning point was when the user said "fix real things." Three
concrete fixes (dirty_repos perf, response shape, apply-proposal bug)
shipped in one commit and produced more user-visible improvement than
the entire meta-AI stack.

**Implication:** observation infrastructure is necessary but not
sufficient. At some point you have to stop building telescopes and
start moving the thing you're looking at.

## 5. Your priors are miscalibrated for the user's context

I repeatedly applied generic SRE caution:
- "Don't over-engineer" → wrong for an AI-engineering lab
- "Wait for data before building" → wrong when the deliverable IS the experience
- "Surface area is small" → a feature (safe lab), not a bug
- "Auto-apply is scary" → wrong for a single-user local tool

The user called this out directly: "your priors are probably informing
you incorrectly." Running it through the research.md scoring confirmed
it — the "build everything now" option won 25/23/20.

**Implication:** when the user overrides your caution with domain
expertise, trust the override. Especially when they're an experienced
AI engineer and you're applying generic software engineering heuristics.

## 6. Skills are the right primitive for LLM-driven agents

I built A1/A2 as Python functions calling `claude -p` via subprocess.
The user caught this immediately: "I wouldn't have built software for
this — I would have written skills for each layer."

Skills run in the Claude Code agent loop. No subprocess. No async/sync
mismatch. No blocking the MCP server. The skill file IS the prompt.
A2 proposing "edit A1's prompt" becomes "edit A1's SKILL.md" — the
same file, the same shape.

**Implication:** check what primitives the environment provides before
reaching for general-purpose code. The right abstraction was already
there; I just didn't see it because I was in "write Python" mode.

## 7. Use the execution framework continuously, not ceremonially

I earned the A1+A2 decision through the trilogy (research.md → visionlog
→ ike.md) properly. Then dropped it for all subsequent work — shipped 7
commits with no ike task updates, no guardrail checks, no decision trail.

The user called this out. The reconciliation commit was honest about it:
"the trilogy was used for the big decision but dropped for execution."

**Implication:** task tracking and guardrail checking are execution
habits, not one-time ceremonies. If the system exists, use it on every
commit, not just the architectural ones.

## 8. The self-improvement loop has diminishing but non-zero returns

| Iterations | Impact level | Examples |
|---|---|---|
| 1-3 | Major bugs | obs-003 (95s tools), obs-004 (fake errors), 13.3GB cleanup |
| 4-6 | Real features | stop words, temporal search, L2 fallback, benchmark |
| 7-10 | Polish + coverage | project filters, crash context, MCP integration tests |
| 11-15 | Maintenance + packaging | rich pin, pyright config, v0.4.1, dep stubs |
| 16+ | Novelty shake needed | what_changed (new tool category) |

**Implication:** the loop produces real value for ~10 iterations, then
needs a "shake of the soda can" — a fundamentally different angle. The
user noticed this before I did: "self-improvement every so often needs
a shake." Without the shake, you grind on the same surface forever.

## 9. Clean up your artifacts

Fast iteration produces waste:
- 13.3 GB telemetry file (recursive bloat artifact)
- Stale known-issues entries (said "no fix shipped" for things fixed 3 commits ago)
- Dead code (`_extract_last_user_message` replaced but not deleted)
- Duplicate section headers in docs
- Multiple active cron jobs from loop restarts

**Implication:** periodic cleanup is real work. Budget time for it.
The known-issues catalogue was the most effective cleanup tool — it
forced accuracy about what was fixed and what wasn't.

## 10. The human should manage the process, not the output

The user's key insight: "I am the human who manages THAT AI" — not A1
(product AI), but A2 (process AI). The human evaluates how the
evaluator evaluates, not what the product AI recommends.

This is the manager-of-managers pattern. It scales because improving
the process compounds across all future product decisions. The user
was right; my instinct to have the human review A1's output directly
was the lower-leverage choice.

**Implication:** when designing AI management loops, put the human
at the highest-leverage layer. Their time is the binding constraint;
spend it on process design, not individual output review.

---

## Summary

The most important thing we learned: **self-improvement works when
it's grounded in measurement, not vibes.** The benchmark turned search
quality from "seems fine" to "77% → 83%." The telemetry turned tool
performance from "feels slow" to "3071ms → 2ms cached." The known-issues
catalogue turned product health from "I think we fixed that" to
"10 of 11 FIXED with commit refs and test references."

Without measurement, self-improvement is just self-activity.
