# Known Issues — resume-resume

Structured catalogue of product issues, kept in source control so the
telemetry pyramid (A1, A2) and humans can read from a single source of
truth instead of rediscovering the same problems every run.

**Updating this file:**
- Add a new entry any time you observe a real issue you can't immediately fix.
- When you fix one, move it to the commit message and delete the entry
  (or strike it through if you want a visible record).
- Each entry should have a perf-regression test where possible; link it
  in the `Test` field.
- A1 and A2 are instructed to consult this file before drafting
  recommendations — don't re-propose things that are already here.

**Severity:**
- ★★★ = blocks real work, user-visible
- ★★  = noticeable friction, slows down workflow
- ★   = paper cut / polish

---

## Performance

### perf-001: `dirty_repos` cold-path scan is slow

- **Severity:** ★★
- **Evidence:** 3071ms p95 in A1's first telemetry observation. After
  29d2f73 optimizations (combined status+branch, skip git-log for clean
  repos), measured ~2000ms on the same machine state (30 repos: 21 clean,
  9 dirty).
- **Why it sucks:** `boot_up` calls `dirty_repos`; user waits ~2 seconds
  on every session resume. Not fatal, but visible friction every session.
- **Workaround:** 30-second result cache (29d2f73) makes subsequent calls
  in the same session ~2ms.
- **Further improvements shipped (this commit):**
  1. ~~Skip project dirs not touched in 30+ days~~ DONE — 63 of 90
     repos skipped on measured run. Remaining 27 scanned.
  2. ~~Increase `ThreadPoolExecutor` workers above 8~~ DONE — bumped to 16.
  3. Stale-while-revalidate: return cached result instantly and refresh
     in background. NOT YET — future work.
- **Test:** `tests/test_perf_regression.py::test_dirty_repos_cold_under_generous_ceiling`
  and `test_dirty_repos_cached_is_dramatically_faster_than_cold`

### perf-002: `recent_sessions` is slow (FIXED 7b2d2d4)

- Fixed. 10-second TTL cache. Cold path still ~1200ms (upstream
  `find_all_sessions`), cached path ~2ms.
- **Test:** `tests/test_perf_regression.py::test_recent_sessions_cached_is_fast`

### perf-003: `self_insights` has no cache (FIXED 7b2d2d4)

- Fixed. 15-second TTL cache keyed by `days` parameter. Currently ~4ms
  uncached, ~0ms cached.
- **Test:** `tests/test_perf_regression.py::test_self_insights_cached_is_flagged`

---

## Correctness

### correctness-001: `_apply_proposal` couldn't handle JSON-string diffs (FIXED 29d2f73)

- Fixed. Retained here as a documented failure-mode-to-test.
- **Test:** `tests/test_meta_ai.py::test_decide_approve_prompt_edit_json_string_form`
- **Why it mattered:** MCP transport serialized a dict `diff` parameter
  into a JSON-encoded string. The apply branches expected either a dict
  or a bare markdown string — neither branch matched a string starting
  with `{"full_new_text": ...`. Approval would have silently failed with
  `apply_error` set. Fixed by `_coerce_diff` which best-effort
  json-decodes strings that look like JSON before dispatching.

### correctness-002: `self_*` list tools used to return bare lists (FIXED 29d2f73)

- Fixed. `fastmcp` serializes bare list returns as `{"result": [...]}`,
  which is inconsistent with tools returning dicts directly. Nine
  self_* tools now return `{"items": [...], "count": N}`.
- **Test:** `tests/test_perf_regression.py::test_self_list_tools_return_wrapped_dict`
- **Why it mattered:** Non-uniform response shape across the MCP surface
  made clients (including me, as an A1/A2 skill) handle each tool
  specially. Wrapping is uniform now.

---

## Observability

### obs-001: Telemetry thresholds miscalibrated below ~100 calls (FIXED 7b2d2d4)

- Fixed. Added `dead_tool_min_volume=100` to thresholds.json. Below that
  volume, `insights_report` returns empty `dead_tools` list with
  `dead_tools_suppressed_below_volume=true`. A2 proposal `f41baad32ae3`
  (low-volume noise guardrail for A1's prompt) was approved and applied.
- **Test:** `tests/test_perf_regression.py::test_obs001_*` (2 tests with
  synthetic telemetry at 50 and 200 calls)

### obs-002: Telemetry JSONL files grow unbounded (FIXED 6c37624)

- Fixed. Gzip rotation (7-day old files), retention via
  `RESUME_RESUME_TELEMETRY_RETENTION_DAYS` env var, reader handles
  `.jsonl.gz` transparently.
- **Test:** `tests/test_telemetry.py::test_gzip_rotation_*` (3 tests)

### obs-003: Recursive telemetry bloat on self_* tools (FIXED this session)

- **Severity:** ★★★ (was blocking)
- **Evidence:** `self_recent_calls` avg 95,369ms (95 seconds!) because
  the middleware logged full results for self_* tools — which contain
  prior telemetry entries, which contain prior results, creating O(n^2)
  JSONL line growth. `self_slow_calls` 83s, `self_errors` 98s, same cause.
- **Fix:** Two-layer defense: (1) self_* tools always log truncated
  results (size + tool_is_self flag, no content), (2) all other tools
  have a 10KB result cap with truncation marker if exceeded.
- **Test:** existing middleware tests verify event structure; the fix
  prevents future blowup by construction.

---

## Infrastructure / Dev ergonomics

### obs-004: Test calls pollute production telemetry (FIXED 817d88a)

- Fixed. `tests/conftest.py` sets `RESUME_RESUME_TELEMETRY=0` at import
  time. Individual tests that need telemetry ON re-enable via monkeypatch.
- Bonus: test suite runtime dropped from ~120s to ~32s.

### dx-001: No integration tests for most `self_*` MCP tools (FIXED 4d940c7)

- Fixed. `tests/test_mcp_surface.py` — 17 integration tests via
  `fastmcp.Client`. Covers dict-returning tools (key presence),
  list-returning tools ({items, count} shape), validation rejections,
  core tool smoke, and A2 scorecard.

### dx-002: `pyright` can't resolve some internal imports (FIXED this session)

- Fixed. Added `pyrightconfig.json` with pyenv venv path, python 3.12,
  extraPaths for claude-session-commons, and basic type checking mode.
  Remaining Pyright warnings are demoted to warnings (not errors).

---

## Meta / process

### process-001: A1 surface area is small; meta-layer value won't show until volume grows

- **Severity:** N/A (a known tradeoff, not a bug)
- **Evidence:** First A1 run filed 1 recommendation for a problem that
  was already visible in raw telemetry. First A2 run filed 1 proposal
  codifying a rule A1 had already followed correctly. At current volume
  the pyramid produces meta-activity more than product progress.
- **Why it's documented:** research ADR-002 anticipated this, but the
  observation is worth keeping visible so future work isn't mistaken for
  pyramid-failure when it's actually pyramid-at-low-volume. Re-evaluate
  when total_calls > 500.
- **Reference:** `.research/DECISION.md`, `.visionlog/adr/ADR-002-*.md`
