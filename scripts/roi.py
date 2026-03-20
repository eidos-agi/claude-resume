#!/usr/bin/env python3
"""
claude-resume ROI calculator.

Estimates:
  - How often you use claude-resume (sessions recovered, searches run)
  - How much time it saves you
  - Token cost of Haiku summaries vs Claude Max subscription budget
"""

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


# ── Config ─────────────────────────────────────────────────────────────────────

CACHE_DIR = Path.home() / ".claude/resume-summaries"
PROJECTS_DIR = Path.home() / ".claude/projects"

# Time savings estimates (minutes) per operation
TIME_SAVINGS = {
    "tui_recovery": 7,       # manual: browse dirs, read JSONL, reconstruct --resume cmd
    "mcp_search": 10,        # manual: grep thousands of files, find the right session
    "mcp_merge": 20,         # manual: read session, copy-paste relevant context
    "mcp_boot_up": 5,        # manual: check recent files, guess which sessions matter
}

# Haiku pricing (per million tokens, as of 2025)
# claude-haiku-3: $0.25 input / $1.25 output
HAIKU_INPUT_PER_M = 0.25
HAIKU_OUTPUT_PER_M = 1.25

# Estimated tokens per summary operation
AVG_INPUT_TOKENS = 1_200    # session context fed to Haiku
AVG_OUTPUT_TOKENS = 350     # summary returned

# Claude Max subscription
CLAUDE_MAX_MONTHLY = 100.0


# ── Helpers ────────────────────────────────────────────────────────────────────

def load_cache_files():
    if not CACHE_DIR.exists():
        return []
    files = []
    for f in CACHE_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            data["_path"] = f
            data["_mtime"] = f.stat().st_mtime
            files.append(data)
        except Exception:
            continue
    return files


def count_project_sessions(project_name: str) -> int:
    """Count sessions in a given project directory (by partial name match)."""
    if not PROJECTS_DIR.exists():
        return 0
    count = 0
    for project_dir in PROJECTS_DIR.iterdir():
        if project_name.lower() in project_dir.name.lower():
            count += len(list(project_dir.glob("*.jsonl")))
    return count


def scan_sessions_for_mcp_usage(limit: int = 500) -> dict:
    """
    Sample recent sessions to count claude-resume MCP tool calls.
    Returns counts per tool.
    """
    if not PROJECTS_DIR.exists():
        return {}

    tool_counts = defaultdict(int)
    resume_tools = {
        "search_sessions", "read_session", "recent_sessions",
        "session_summary", "boot_up", "resume_in_terminal",
        "merge_context", "session_timeline", "session_thread",
        "session_insights", "session_xray", "session_report",
        "session_data_science",
    }

    sessions_checked = 0
    all_jsonl = sorted(
        PROJECTS_DIR.glob("*/*.jsonl"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )

    for jsonl in all_jsonl[:limit]:
        try:
            text = jsonl.read_bytes().lower()
            # Quick pre-filter: skip if no claude-resume mention
            if b"claude-resume" not in text and b"search_sessions" not in text and b"boot_up" not in text:
                continue
            with open(jsonl, "r", errors="replace") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    msg = entry.get("message", {})
                    content = msg.get("content", []) if isinstance(msg, dict) else []
                    if not isinstance(content, list):
                        continue
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            name = block.get("name", "")
                            if name in resume_tools:
                                tool_counts[name] += 1
            sessions_checked += 1
        except Exception:
            continue

    return dict(tool_counts)


def build_usage_timeline(cache_files: list) -> dict:
    """Build month-by-month summary of summarized sessions."""
    by_month = defaultdict(lambda: {"interactive": 0, "automated": 0, "total": 0})
    for c in cache_files:
        mtime = c.get("_mtime", 0)
        dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
        key = dt.strftime("%Y-%m")
        classification = c.get("classification", "unknown")
        by_month[key]["total"] += 1
        if classification == "interactive":
            by_month[key]["interactive"] += 1
        else:
            by_month[key]["automated"] += 1
    return dict(sorted(by_month.items()))


def estimate_tokens_used(summarized_count: int) -> dict:
    """Estimate Haiku token usage and cost for N summaries."""
    input_tokens = summarized_count * AVG_INPUT_TOKENS
    output_tokens = summarized_count * AVG_OUTPUT_TOKENS
    input_cost = (input_tokens / 1_000_000) * HAIKU_INPUT_PER_M
    output_cost = (output_tokens / 1_000_000) * HAIKU_OUTPUT_PER_M
    total_cost = input_cost + output_cost
    return {
        "summaries": summarized_count,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "input_cost_usd": input_cost,
        "output_cost_usd": output_cost,
        "total_cost_usd": total_cost,
    }


def fmt_mins(minutes: float) -> str:
    if minutes < 60:
        return f"{minutes:.0f} min"
    h = minutes / 60
    return f"{h:.1f} hrs"


def fmt_usd(amount: float) -> str:
    if amount < 0.01:
        return f"${amount:.4f}"
    return f"${amount:.2f}"


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("\n━━━ claude-resume ROI calculator ━━━\n")

    # 1. Cache overview
    print("Scanning summary cache…")
    cache_files = load_cache_files()
    total_cached = len(cache_files)
    interactive = sum(1 for c in cache_files if c.get("classification") == "interactive")
    automated = total_cached - interactive
    summarized = sum(1 for c in cache_files if c.get("summary"))

    print(f"  {total_cached:,} sessions cached")
    print(f"  {interactive:,} interactive  |  {automated:,} automated/bot")
    print(f"  {summarized:,} have AI summaries generated")

    # 2. Timeline
    timeline = build_usage_timeline(cache_files)
    if timeline:
        print(f"\n  Monthly activity (sessions indexed):")
        for month, counts in list(timeline.items())[-6:]:
            bar = "█" * min(40, counts["total"] // 10)
            print(f"    {month}  {bar}  {counts['interactive']} human / {counts['total']} total")

    # 3. MCP tool usage
    print("\nScanning recent sessions for MCP tool usage (this takes ~10s)…")
    tool_counts = scan_sessions_for_mcp_usage(limit=300)

    total_searches = tool_counts.get("search_sessions", 0)
    total_merges = tool_counts.get("merge_context", 0)
    total_boots = tool_counts.get("boot_up", 0)

    if tool_counts:
        print(f"\n  MCP tool calls found (sampled last 300 sessions):")
        for tool, count in sorted(tool_counts.items(), key=lambda x: -x[1]):
            print(f"    {tool:<30} {count:>5}")
    else:
        print("  No MCP usage found in sampled sessions.")

    # 4. Time savings estimate
    print("\n━━━ Time savings estimate ━━━\n")

    # TUI recoveries: estimate from interactive sessions with resumability scores
    resumable = sum(
        1 for c in cache_files
        if c.get("classification") == "interactive"
        and (c.get("resumability_score") or 0) > 0.3
    )

    tui_time = resumable * TIME_SAVINGS["tui_recovery"]
    search_time = total_searches * TIME_SAVINGS["mcp_search"]
    merge_time = total_merges * TIME_SAVINGS["mcp_merge"]
    boot_time = total_boots * TIME_SAVINGS["mcp_boot_up"]
    total_time = tui_time + search_time + merge_time + boot_time

    print(f"  TUI recoveries         ~{resumable:,} sessions   → {fmt_mins(tui_time)} saved  ({TIME_SAVINGS['tui_recovery']} min/session)")
    print(f"  MCP search_sessions    ~{total_searches:,} calls      → {fmt_mins(search_time)} saved  ({TIME_SAVINGS['mcp_search']} min/call)")
    print(f"  MCP merge_context      ~{total_merges:,} calls      → {fmt_mins(merge_time)} saved  ({TIME_SAVINGS['mcp_merge']} min/call)")
    print(f"  MCP boot_up            ~{total_boots:,} calls      → {fmt_mins(boot_time)} saved  ({TIME_SAVINGS['mcp_boot_up']} min/call)")
    print(f"\n  Total estimated time saved: {fmt_mins(total_time)}")
    if total_time > 0:
        days = total_time / (60 * 8)
        print(f"  ≈ {days:.1f} full work days")

    # 5. Token cost
    print("\n━━━ Token cost (Haiku summaries) ━━━\n")

    tokens = estimate_tokens_used(summarized)
    print(f"  Summaries generated:   {tokens['summaries']:,}")
    print(f"  Input tokens:          {tokens['input_tokens']:,}  ({fmt_usd(tokens['input_cost_usd'])})")
    print(f"  Output tokens:         {tokens['output_tokens']:,}  ({fmt_usd(tokens['output_cost_usd'])})")
    print(f"  Total Haiku API cost:  {fmt_usd(tokens['total_cost_usd'])}")

    # vs Claude Max
    pct_of_max = (tokens["total_cost_usd"] / CLAUDE_MAX_MONTHLY) * 100
    print(f"\n  Claude Max subscription: ${CLAUDE_MAX_MONTHLY:.0f}/month")
    print(f"  Haiku cost as % of Max:  {pct_of_max:.2f}%")

    if total_time > 0:
        # Monthly estimate (assume ~12 months of data)
        months = max(1, len(timeline))
        monthly_cost = tokens["total_cost_usd"] / months
        monthly_time = total_time / months
        print(f"\n  Per month (avg over {months} months):")
        print(f"    Haiku spend:         {fmt_usd(monthly_cost)}")
        print(f"    Time saved:          {fmt_mins(monthly_time)}")
        if monthly_cost > 0:
            mins_per_dollar = monthly_time / monthly_cost
            print(f"    Efficiency:          {mins_per_dollar:,.0f} minutes saved per dollar spent")

    print(f"\n  Note: Summaries are cached permanently after first generation.")
    print(f"  Subsequent searches and TUI launches for the same sessions cost $0.\n")


if __name__ == "__main__":
    main()
