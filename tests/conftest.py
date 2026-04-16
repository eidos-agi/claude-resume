"""Pytest configuration for resume-resume tests.

Disables telemetry capture during test runs so test tool calls don't
pollute production telemetry (obs-004). Without this, every pytest run
generates JSONL entries that A1/A2 read as real usage data — the
self_process_decide "83% error rate" was entirely test noise.
"""

import os

# Disable telemetry before any resume_resume module is imported.
# This must happen at conftest load time, not in a fixture, because
# the TelemetryMiddleware checks the env var on each call.
os.environ["RESUME_RESUME_TELEMETRY"] = "0"
