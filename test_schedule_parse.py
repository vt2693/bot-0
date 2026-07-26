#!/usr/bin/env python
"""Test harness for HermesBridge._parse_deterministic().

Usage:
    python test_schedule_parse.py

Tests all deterministic schedule patterns without any LLM calls.
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from hermes_bridge import HermesBridge


class FakeSettings:
    provider_name = "none"
    ROUTER_0_API_KEY = ""
    ROUTER_0_BASE_URL = ""
    ROUTER_0_MODEL = ""
    OPENCODE_ZEN_API_KEY = ""
    OPENCODE_ZEN_MODEL = ""
    OPENCODE_ZEN_BASE_URL = ""
    OPENROUTER_API_KEY = ""
    OPENROUTER_MODEL = ""
    OPENROUTER_BASE_URL = ""
    SYSTEM_PROMPT = ""
    MAX_TOKENS = 200
    TEMPERATURE = 0.7
    TOOL_LOOP_MAX_ROUNDS = 1
    LLM_TIMEOUT = 30
    MEMORY_ENABLED = False
    MEMORY_AUTO_EXTRACT = False
    AUTO_LEARN = False


bridge = HermesBridge(FakeSettings())

passed = 0
failed = 0


def check(label: str, text: str, expected: dict | None, not_keys: list[str] | None = None):
    global passed, failed
    result = bridge._parse_deterministic(text)
    ok = True

    if expected is None:
        if result is not None:
            print(f"  FAIL  {label}: got {result}, expected None")
            ok = False
        else:
            passed += 1
            print(f"  PASS  {label}")
            return

    if result is None:
        print(f"  FAIL  {label}: got None, expected {expected}")
        failed += 1
        return

    for k, v in expected.items():
        if k not in result:
            print(f"  FAIL  {label}: missing key '{k}' in {result}")
            ok = False
        elif v is not None and result[k] != v:
            if k == "prompt" and isinstance(v, str) and isinstance(result[k], str) and result[k].strip() == v.strip():
                continue
            if isinstance(v, int) and isinstance(result[k], int) and abs(result[k] - v) <= 30:
                continue
            if k == "absolute_epoch" and isinstance(result[k], int) and result[k] > int(time.time()) - 60:
                continue
            print(f"  FAIL  {label}: '{k}' expected {v!r}, got {result[k]!r}")
            ok = False

    if not_keys:
        for k in not_keys:
            if k in result:
                print(f"  FAIL  {label}: unexpected key '{k}' in {result}")
                ok = False

    if ok:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1


def epoch_after(h: int, m: int) -> int:
    """Compute the next occurrence of HH:MM in local time."""
    lt = time.localtime()
    target = int(time.mktime((
        lt.tm_year, lt.tm_mon, lt.tm_mday, h, m, 0, 0, 0, -1
    )))
    now = int(time.time())
    if target <= now:
        target += 86400
    return target


print("=" * 60)
print("HermesBridge._parse_deterministic() tests")
print("=" * 60)

# ── Interval patterns ──

check("every N minutes",
      "check gmail every 15 minutes",
      {"interval_minutes": 15, "prompt": "check gmail"})

check("every N minutes (prompt first)",
      "every 15 minutes check gmail",
      {"interval_minutes": 15, "prompt": "check gmail"})

check("every N minutes (no verb → LLM fallback)",
      "every 15 minutes",
      None)

check("every N min (short form)",
      "summarize news every 5 min",
      {"interval_minutes": 5, "prompt": "summarize news"})

check("every N hours",
      "scan server every 2 hours",
      {"interval_minutes": 120, "prompt": "scan server"})

check("every N hour (singular)",
      "backup every 1 hour",
      {"interval_minutes": 60, "prompt": "backup"})

check("hourly",
      "hourly report",
      {"interval_minutes": 60, "prompt": "report"})

check("every hour",
      "check status every hour",
      {"interval_minutes": 60, "prompt": "check status"})

check("daily (interval, no time)",
      "daily backup",
      {"interval_minutes": 1440, "prompt": "backup"})

check("every day (interval, no time)",
      "send report every day",
      {"interval_minutes": 1440, "prompt": "send report"})

check("every other day",
      "sync every other day",
      {"interval_minutes": 2880, "prompt": "sync"})

check("twice a day",
      "check status twice a day",
      {"interval_minutes": 720, "prompt": "check status"})

check("in 30 minutes",
      "remind me in 30 minutes",
      {"interval_minutes": 30, "prompt": "remind me"})

# ── Absolute epoch patterns ──

check("every day at HH:MM ampm",
      "provide weather forecast every day at 6 am",
      {"prompt": "provide weather forecast"},
      not_keys=["interval_minutes"])

check("daily at HH:MM",
      "check mail daily at 8 am",
      {"prompt": "check mail"},
      not_keys=["interval_minutes"])

check("at HH:MM ampm",
      "call mom at 5 pm",
      {"prompt": "call mom"},
      not_keys=["interval_minutes"])

check("at HH:MM (no ampm, 24h)",
      "scan network at 14:30",
      {"prompt": "scan network"},
      not_keys=["interval_minutes"])

check("tomorrow at HH:MM",
      "deploy tomorrow at 9 am",
      {"prompt": "deploy"},
      not_keys=["interval_minutes"])

check("at noon",
      "meeting at noon",
      {"prompt": "meeting"},
      not_keys=["interval_minutes"])

check("at midnight",
      "batch job at midnight",
      {"prompt": "batch job"},
      not_keys=["interval_minutes"])

# ── Edge cases ──

check("time expr in middle of text",
      "check at 3pm the server logs",
      {"prompt": "check the server logs"},
      not_keys=["interval_minutes"])

check("no scheduling intent → None",
      "hello how are you",
      None)

check("just a number → None",
      "42",
      None)

check("complex (LLM fallback)",
      "scan at 3pm on friday",
      None)

check("in N + trailing prompt",
      "summarize in 10 minutes the report",
      {"interval_minutes": 10, "prompt": "summarize the report"})

check("every weekday at time",
      "standup every weekday at 9 am",
      {"prompt": "standup"},
      not_keys=["interval_minutes"])

check("weekdays at time",
      "status weekdays at 5 pm",
      {"prompt": "status"},
      not_keys=["interval_minutes"])

check("daily (interval, no time stated)",
      "send report every day",
      {"interval_minutes": 1440, "prompt": "send report"})

# ── am/pm boundary cases ──
check("12am = midnight",
      "fire at 12 am",
      {"prompt": "fire"},
      not_keys=["interval_minutes"])

check("12pm = noon",
      "lunch at 12 pm",
      {"prompt": "lunch"},
      not_keys=["interval_minutes"])

# ── The original bug case ──
check("BUG REPRODUCER: provide weather forecast every day at 6 am",
      "provide weather forecast every day at 6 am",
      {"prompt": "provide weather forecast"},
      not_keys=["interval_minutes"])

# ── Summary ──
print()
print("=" * 60)
total = passed + failed
print(f"  {total} tests: {passed} passed, {failed} failed")
print("=" * 60)
sys.exit(0 if failed == 0 else 1)
