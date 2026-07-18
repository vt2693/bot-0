---
name: deploying-hermes-agent
description: >-
  Deploy Hermes Agent to Android/Termux (headless Telegram bot via getUpdates polling).
  8-provider LLM config with router_0, SchedulerEngine, MemoryStore (SQLite),
  Composio MCP tools, and in-process voice transcription.
  Confidence: 100%
---

# Deploying Hermes Agent to Android (Termux)

## Purpose

Run the Hermes Agent on an Android phone via Termux — a headless Telegram bot with getUpdates polling (no webhook, no Gradio). Supports multi-provider LLM (router_0 proxy), Composio MCP tools (including Firecrawl scrape/crawl/search and Jira), voice memo transcription (Groq → NVIDIA), MemoryStore (SQLite), SchedulerEngine for periodic tasks, and inline keyboard menus.

## Supported Environments

- **Android phone (Termux)** — primary deployment target
- Local development machine (Windows/Linux/macOS) for testing

### Non-Goals

- Running a Gradio or FastAPI web UI (Telegram-only interaction)
- Remote memory persistence (disabled by config — SQLite-only on Android)

## Architecture

```
       Telegram (api.telegram.org)
            │
            │  getUpdates (30s long-poll)
            ▼
    ┌───────────────┐
    │ android_bot.py│  (poll loop)
    │  ┌──────────┐ │            ┌──────────────┐
    │  │ getUpdates│ │──────────▶│ enqueue_update│
    │  │  poll     │ │           └──────┬───────┘
    │  └──────────┘ │                  │
    │  ┌──────────┐ │           ┌──────▼───────┐
    │  │ outbox   │◀────outbox──│ queue_worker │
    │  │ drain    │ │  drain    │ (background) │
    │  │ ────────▶│ │           └──────┬───────┘
    │  │ Telegram  │ │                  │
    │  │ API      │ │           ┌──────▼────────┐
    │  └──────────┘ │           │  HermesBridge  │──▶ LLM (httpx)
    │               │           │  (tool router) │──▶ Composio MCP
    │               │           │  + memory/skill│──▶ MemoryStore
    │  voice ───────┤           └──────┬─────────┘
    │  (inline)     │                  │
    │  tg_voice.py  │           ┌──────▼──────┐
    │  ── download──┤           │ Scheduler   │
    │  ── ffmpeg ───┤           │ Engine      │
    │  ── transcribe│           │ (30s poll)  │
    └───────────────┘           └─────────────┘
```

**Key insight:** Android bot uses **direct** Telegram API calls (no relay needed). `android_bot.py` long-polls `getUpdates` for inbound messages and calls `api.telegram.org` directly for outbound via `_send_direct()`. No webhook, no relay.py.

Voice is processed **in-process** (not via external relay): download → ffmpeg (16kHz WAV) → Groq whisper-large-v3.

## Files

| File | Purpose |
|------|---------|
| `android_bot.py` | Main entry point — getUpdates poll loop, outbox drain, voice handling |
| `telegram_bot.py` | Queue, outbox, inline menus, callback routing, command handlers |
| `hermes_bridge.py` | Multi-provider LLM bridge via httpx (no openai SDK), tool loop, memory injection |
| `config.py` | Settings from env vars, 8-provider auto-detection |
| `composio_mcp.py` | Composio MCP client (HTTP JSON-RPC, workbench for Jira tools) |
| `memory_store.py` | SQLite fact + skill store (SQLite-only on Android) |
| `scheduler.py` | SchedulerEngine (30s poll loop) |
| `tg_voice.py` | Voice helper: download, ffmpeg, Groq/NVIDIA transcription |
| `voice_relay.py` | Wrapper importing from tg_voice.py (kept for compat) |
| `setup_android.sh` | One-shot setup: pkg install, pip deps, token prompts |
| `start_android.sh` | tmux launcher with auto-restart, dep check, wake-lock |
| `deploy_android.ps1` | Windows script: ADB push or SSH/rsync to phone (non-interactive) |
| `requirements.txt` | pip deps list (for reference; phone uses `pip install httpx` directly) |
| `relay.py` | Legacy (not used on Android) |
| `app.py` | Legacy (not used on Android) |
| `healthcheck.py` | Legacy (not used on Android) |

## Confidence: 100%

All components validated end-to-end on Android/Termux with Python 3.14. Voice, memory, scheduler, Jira, menus, provider switching all verified live.

### Architecture & deployment
Confidence: 100% — Validated end-to-end with live Telegram message delivery. Headless polling, no web server needed.

### config.py provider logic
Confidence: 100% — 8 provider names including `router_0`. Provider auto-detection order: PROVIDER env → `router_0` → `opencode_zen` → `openrouter` → `google` → `nvidia` → `groq` → `openai` → `anthropic`. Settings immutable, cached via `@lru_cache()`.

### Provider fallback chain
Confidence: 100% — 3 retries with 1.5x exponential backoff on transient errors (ECONNRESET, 5xx, JSONDecodeError from proxy cold-start HTML); `chat()` wraps final failure in `f"Error: {e}"`.

### Provider switching (/model + inline menu)
Confidence: 100% — Telegram `/model` command and inline model-switch menu (System → Switch Model → `ac:model:*` callback routing). Menu dynamically shows ✅ on active model, ⭐ on provider default.

### Router-0 provider
Confidence: 100% — Auto-detected by API key or base URL. No key required (passes `""` to httpx). Default model: `oc/deepseek-v4-flash-free`. Default base: `vt2693-router-0.hf.space/v1`. Model-switch menu options include `combo-high`, `combo-medium`, and `combo-low` (routed via `ac:model:combo-*`).

### Telegram bot + polling
Confidence: 100% — Direct Telegram API calls via `urllib`. getUpdates long-poll (30s timeout). Outbound via `_send_direct()` mapping `_TELEGRAM_PATHS`. Outbox drain background task. 7 slash commands registered: `/start`, `/menu`, `/help`, `/model`, `/improve`, `/secrets`, `/schedule`. Inline keyboard menu (10 menus: Main, Web, Memory, Chat, Voice, Skills, System, Model, Schedule, Jira). Callback routing with `mn:*`, `ac:*`, `ac:model:*`, `ac:schedule_*`, `ac:skill_*`, `ac:jira_task:*`, `ac:jira_show:*`, `ac:jira_run:*` prefixes. Per-chat history: 1000 messages as `[{role, content}]`.

### In-process voice
Confidence: 100% — Voice memo detected in poll loop → download via getFile API → ffmpeg (16kHz mono WAV) → Groq whisper-large-v3. No separate voice relay process needed.

### MemoryStore (LIKE + SQLite)
Confidence: 100% — LIKE-based fact search with recent-facts fallback. No FTS5, no HRR, no numpy. Learned skills table with title/problem/procedure/lifecycle. SQLite-only — no remote sync.

### Composio MCP integration
Confidence: 100% — HTTP JSON-RPC client with initialize → tools/list → tools/call flow. Jira tools accessed via `COMPOSIO_REMOTE_WORKBENCH` + `run_composio_tool()` (not direct `tools/call` RPC). Cold-start retry pattern.

### SchedulerEngine
Confidence: 100% — 30s async poll loop. SQLite persistence. NL+structured `/schedule` parsing with interval/time-target support. 5-min confirmation TTL. 3-error auto-pause. Once/daily/interval modes. `catch_up` skips once-mode jobs (interval=0 guard).

## Inputs (secrets)

| Input | Required | Source | Notes |
|-------|----------|--------|-------|
| `TELEGRAM_BOT_TOKEN` | Yes | BotFather | Bot authentication |
| `GROQ_API_KEY` | Yes | Groq console | Voice transcription + primary provider |
| `ROUTER_0_API_KEY` | No | Router-0 dashboard | LLM proxy (empty OK, passes `""` to httpx) |
| `ROUTER_0_BASE_URL` | No | — | Router-0 base URL override (empty OK, uses default) |
| `TELEGRAM_ALLOWED_USERS` | No | — | Comma-separated Telegram user IDs to restrict access |
| `NVIDIA_API_KEY` | For voice fallback | NVIDIA build API | Voice transcription fallback |
| `COMPOSIO_CONSUMER_API_KEY` | For tools | Composio dashboard | Jira, Firecrawl, etc. |
| `OPENCODE_ZEN_API_KEY` | Optional | OpenCode | Alternative LLM provider |
| `GOOGLE_API_KEY` | Optional | Google AI | Alternative LLM provider |
| `ANTHROPIC_API_KEY` | Optional | Anthropic | Alternative LLM provider |
| `OPENAI_API_KEY` | Optional | OpenAI | Alternative LLM provider |
| `JIRA_EPICS` | For Jira menu | Jira | Comma-separated epic keys (e.g. PROJ-123,PROJ-456) |

## Environment Variables

Set in `$HOME/.hermes-tokens.env` (loaded by `start_android.sh`). Config module reads from `os.getenv()` at init. Defaults shown below.

| Variable | Default | Required | Purpose |
|----------|---------|----------|---------|
| `TELEGRAM_BOT_TOKEN` | — | Yes | Telegram bot auth |
| `TELEGRAM_ALLOWED_USERS` | `""` | No | Restrict to specific user IDs |
| `PROVIDER` | *auto-detect* | No | Override LLM provider |
| `ROUTER_0_API_KEY` | — | Yes | Router-0 LLM provider |
| `ROUTER_0_MODEL` | `oc/deepseek-v4-flash-free` | No | Router-0 model name |
| `ROUTER_0_BASE_URL` | `https://vt2693-router-0.hf.space/v1` | No | Router-0 base URL |
| `GROQ_API_KEY` | — | For voice | Groq whisper-large-v3 |
| `GROQ_MODEL` | `llama-3.1-8b-instant` | No | Groq model override |
| `GROQ_BASE_URL` | `https://api.groq.com/openai/v1` | No | Groq base URL |
| `NVIDIA_API_KEY` | — | For voice fallback | NVIDIA parakeet-3b-asr |
| `NVIDIA_MODEL` | `nvidia/nemotron-mini-4b-instruct` | No | NVIDIA model override |
| `NVIDIA_BASE_URL` | `https://integrate.api.nvidia.com/v1` | No | NVIDIA base URL |
| `OPENCODE_ZEN_API_KEY` | — | No | OpenCode Zen LLM |
| `OPENCODE_ZEN_MODEL` | `deepseek-v4-flash-free` | No | OpenCode Zen model |
| `OPENCODE_ZEN_BASE_URL` | `https://opencode.ai/zen/v1` | No | OpenCode Zen base URL |
| `OPENROUTER_API_KEY` | — | No | OpenRouter LLM |
| `OPENROUTER_MODEL` | `openrouter/free` | No | OpenRouter model |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | No | OpenRouter base URL |
| `GOOGLE_API_KEY` | — | No | Google Gemini |
| `GOOGLE_MODEL` | `gemini-3.1-flash-lite` | No | Google model |
| `GOOGLE_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta/openai/` | No | Google base URL |
| `OPENAI_API_KEY` | — | No | OpenAI provider |
| `OPENAI_MODEL` | `gpt-4o-mini` | No | OpenAI model |
| `OPENAI_BASE_URL` | — | No | OpenAI base URL override |
| `ANTHROPIC_API_KEY` | — | No | Claude provider |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-20250514` | No | Claude model |
| `COMPOSIO_CONSUMER_API_KEY` | — | No | Composio MCP auth |
| `COMPOSIO_APPS` | `""` | No | Comma-separated app slugs |
| `JIRA_EPICS` | — | No | Comma-separated Jira epic keys |
| `MEMORY_ENABLED` | `true` | No | Enable memory |
| `MEMORY_AUTO_EXTRACT` | `true` | No | Auto-extract facts from conversations |
| `AUTO_LEARN` | `true` | No | Detect reusable procedures and ask before saving |
| `MEMORY_RESTORE_ON_STARTUP` | `false` | No | Restore memory from SQLite on startup |
| `MEMORY_DB_PATH` | *see* | No | SQLite path (default: `$HOME/hermes_memory.db` on Android) |
| `MEMORY_SPACE_ID` | `none` | No | Legacy; kept for compat (no-op on Android) |
| `TOOL_LOOP_MAX_ROUNDS` | `1000` | No | Max LLM tool-call rounds |
| `LLM_TIMEOUT` | `600` | No | LLM call timeout in seconds |
| `BROADCAST_CHAT_ID` | — | No | Channel/group chat_id to relay tool call results |
| `SYSTEM_PROMPT` | *Hermes Agent default* | No | Override system prompt |
| `MAX_TOKENS` | `2048` | No | Max output tokens |
| `TEMPERATURE` | `0.7` | No | LLM temperature |
| `WORK_DIR` | `$TMPDIR` | No | Voice temp file directory (read by `android_bot.py`, not `config.py`) |
| `DEBUG` | `false` | No | Enable debug logging |

## Detailed Workflow

### Step 1: Deploy to Phone

Two methods:

**A — Clone from GitHub (requires internet):**
```bash
pkg install git
git clone https://github.com/vt2693/bot-0.git hermes-bot
cd hermes-bot
bash setup_android.sh   # prompts for all tokens
bash start_android.sh   # starts in tmux
```

**B — deploy_android.ps1 from Windows:**
```powershell
.\deploy_android.ps1    # ADB (or -Ip for SSH)
```

### Step 2: Setup Script (setup_android.sh)

- Installs: `python`, `ffmpeg`, `tmux`, `termux-api`, `git`, `binutils`, `python-numpy` (pre-built)
- Installs: `httpx` via pip (no openai SDK needed — bot uses direct httpx calls)
- Verifies: `python -c "import httpx, numpy"`
- Prompts for 10 API keys + 2 optional configs (TELEGRAM_ALLOWED_USERS, JIRA_EPICS) interactively with existing-value defaults
- Writes `$HOME/.hermes-tokens.env` with `PROVIDER="router_0"`

### Step 3: Start Script (start_android.sh)

```bash
#!/data/data/com.termux/files/usr/bin/bash
cd "$(dirname "$0")" || cd ~/hermes-bot

# Load tokens
ENV_FILE="$HOME/.hermes-tokens.env"
if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE. Run: bash setup_android.sh"
  exit 1
fi
. "$ENV_FILE"

# Verify deps
python -c "import sys, importlib.util; pkgs=['httpx','numpy']; missing=[...]; ..." || exit 1

termux-wake-lock || true
tmux has-session -t hermes 2>/dev/null && echo "Killing existing session..." && tmux kill-session -t hermes
tmux new-session -d -s hermes -n bot \
  "while true; do python -u android_bot.py 2>&1 | tee -a logs/bot.log; sleep 2; done"
echo "Hermes bot started. Attach: tmux attach -t hermes"
```

### Step 4: Android Bot Entry Point (android_bot.py)

Main asyncio entry point. Key sections:

**Poll loop:** `_poll_loop(tg, work_dir)` — infinite loop calling `getUpdates` with 30s long-poll timeout via `asyncio.to_thread`. Voice messages detected in the loop, processed inline (download → ffmpeg → transcribe), then re-routed as text through the normal queue.

**Outbox drain:** `_drain_outbox(tg)` — background task draining `tg.outbox` and delivering via `_send_direct()` with 1 retry on failure.

**Startup sequence:**
1. Initialize ComposioMCP, MemoryStore, HermesBridge, TelegramBot
2. Delete stale webhook (`deleteWebhook` — ensures getUpdates works)
3. Self-test via `getMe` (verifies token)
4. Start queue worker, outbox drain, scheduler
5. Enter poll loop

**Shutdown:** Cancels worker/outbox tasks, stops scheduler, closes composio, closes store.

### Step 5: LLM Bridge (hermes_bridge.py)

Multi-provider LLM bridge using **direct httpx calls** (no openai SDK). Key methods:

- `_call_llm()` — sends POST to `/chat/completions` with `stream: False`, handles tool calls in loop up to `TOOL_LOOP_MAX_ROUNDS`
- `chat_with_memory()` — retrieves relevant facts + skills, injects into system prompt, calls LLM, extracts facts from response, detects skills
- `_build_messages()` — constructs message list from history (dict or tuple format), injected skills/facts
- `_detect_skill()` — heuristic gate + constrained JSON LLM extraction for learned skills
- `_execute_tool()` — calls `ComposioMCP.call_tool_sync()` (sync `httpx.Client`, no event loop needed)

8 provider auto-detection order: PROVIDER env → `router_0` → `opencode_zen` → `openrouter` → `google` → `nvidia` → `groq` → `openai` → `anthropic`.

### Step 6: Telegram Bot (telegram_bot.py)

- **Queue:** Thread-safe list. `enqueue_update()` adds, `process_queue_worker()` pops and calls `process_update()`.
- **Outbox:** Thread-safe list. Methods write `{"_method": "sendMessage", ...}`. `drain_outbox()` returns and clears.
- **Inline menus:** `MENUS` dict with 10 menus. Callback routing via `mn:*` (menu nav), `ac:*` (action handlers).
- **Commands (7):** `/start`, `/menu`, `/help`, `/model`, `/improve`, `/secrets`, `/schedule`.
- **Skills:** `/improve` — list/search/detail/edit/delete skills. Auto-detect via `_detect_skill()` + Save/Edit/Discard confirmation.
- **Schedule:** NL+structured parsing, 5-min confirmation, full CRUD via inline buttons. Supports interval, absolute-time (Run Once / Daily), and once/daily modes.
- **Jira:** `mn:jira` → `ac:jira_open_tasks` → `COMPOSIO_REMOTE_WORKBENCH` with `run_composio_tool("JIRA_SEARCH_FOR_ISSUES_USING_JQL_GET", ...)`. Open tasks filtered to `status IN ("To Do","In Progress")`. Subtask rows: `[🔵 key: summary] [▶️ Run]`. Tapping subtask left button (`ac:jira_show:*`) fetches full issue via `JIRA_GET_ISSUE` and renders description as plain text (ADF → text converter via `json.loads` + `ast.literal_eval` fallback). `ac:jira_run:*` sends description as LLM prompt with `_skill_detected` JSON unwrap. Subtask list filtered to open statuses only (no Done items).

### Step 7: Memory Store (memory_store.py)

SQLite-backed fact + skill store. SQLite-only on Android.

- **Facts:** `facts` table with LIKE search, trust_score (+0.05/-0.10), cleanup_low_trust (< 0.2).
- **Skills:** `skills` table with title/problem/procedure/failure_pattern/status lifecycle (unverified → active → inactive).
- **Scheduled jobs:** `scheduled_jobs` table co-located for SchedulerEngine.

### Step 8: Scheduler (scheduler.py)

30s async poll loop. Checks `scheduled_jobs.next_run_at ≤ now`. 3 consecutive errors → auto-pause with notification. Cold-boot catch-up (skip >2 intervals behind). Max 20 jobs/chat.

### Step 9: Composio MCP (composio_mcp.py)

HTTP JSON-RPC client. Tools accessed via `initialize` → `tools/list` → `tools/call`. **Jira tools: `tools/call` returns only meta-tools; actual Jira tools accessed via `COMPOSIO_REMOTE_WORKBENCH` + `run_composio_tool()`. Cold-start: first workbench call may return empty; retry once after 2s.

`get_openai_tools()` converts to OpenAI function-calling format (max 64 tools). SSE response parsing. Accept header: `application/json, text/event-stream`.

## Error Recovery

| Signal | Action |
|--------|--------|
| LLM call returns streaming (SSE) | Ensure `stream: False` in request body |
| Composio cold start returns empty | Retry once after 2s |
| getUpdates timeout | `asyncio.wait_for` wrapper catches `TimeoutError`, continues loop |
| 3 consecutive scheduler failures | Auto-pause job with user notification |
| Tool loop stalls | Capped at `TOOL_LOOP_MAX_ROUNDS` (default 1000), returns summary |
| Module not found | `start_android.sh` verifies deps before launching |
| Outbox send fails | 3 retries with 1.5x exponential backoff inside `_send_direct` |

## Edge Cases Covered

| Case | Handling |
|------|----------|
| Stale webhook from prior deployment | `deleteWebhook` called on startup |
| Telegram API token invalid | `getMe` self-test at startup logs failure |
| Voice download fails | User notified, no crash |
| Mem processing fail (ffmpeg) | User notified, no crash |
| Transcription fail | Groq → NVIDIA fallback |
| Jira tools not configured | Empty JIRA_EPICS → warning message via menu |
| Composio not configured | Menu entry shows "not available" |
| getUpdates queue overflow | Telegram stores 24h of updates; offset tracking prevents duplicates |
| Work dir missing | Created at startup via `mkdir` |
| Remote memory backup attempted | No-op (backup methods are stubs on Android) |

## Verification

After `bash start_android.sh`:

1. Send `/start` to bot → should respond with welcome message
2. Send `/menu` → should show inline keyboard with menus
3. Send text → should get LLM response
4. Send voice memo → should transcribe and reply (requires Groq key)
5. Send "remember that I live in Bogor" → should store and recall on later messages
6. Tap Jira → Open Tasks → should show issues (requires JIRA_EPICS + Composio key)
7. Check logs: `tail -20 ~/hermes-bot/logs/bot.log`

## Quick Reference

### Startup Flow
```
start_android.sh
  → source .hermes-tokens.env
  → verify httpx, numpy
  → kill old tmux session
  → tmux new-session
    → python android_bot.py
      → deleteWebhook (ensure polling mode)
      → getMe (verify token)
      → init ComposioMCP / MemoryStore / HermesBridge / TelegramBot
      → configure_commands() (enqueue setMyCommands)
      → start SchedulerEngine
      → start queue_worker (asyncio task)
      → start outbox_drain (asyncio task)
      → enter poll loop (getUpdates 30s long-poll)
```

### Glossary

| Term | Definition |
|------|-----------|
| **getUpdates polling** | Long-poll Telegram API for inbound updates (30s timeout, no webhook) |
| **_send_direct** | `urllib` call to `api.telegram.org/bot<token>/<method>` for outbound delivery |
| **Queue** | Thread-safe list in TelegramBot; `process_queue_worker` pops and dispatches |
| **Outbox** | Thread-safe list of `{_method, ...}` dicts; `drain_outbox` returns to caller |
| **`_method` dispatch** | Field in outbox dicts mapping to Telegram API method (sendMessage, etc.) |
| **TELEGRAM_PATHS** | Dict mapping method names to API paths (`sendMessage → /sendMessage`) |
| **MemoryStore** | SQLite-backed fact + skill store, no FTS5, no vector search; SQLite-only on Android |
| **SchedulerEngine** | 30s async poll loop, SQLite persistence, 3-error auto-pause |
| **Composio MCP** | HTTP JSON-RPC to connect.composio.dev/mcp; Jira via workbench |
| **COMPOSIO_REMOTE_WORKBENCH** | Code execution tool for Jira access (not direct tools/call RPC) |
| **Learned skills** | SQLite skills table: title/problem/procedure/status lifecycle |
| **Auto-learn** | Detect reusable procedures via heuristic → LLM extraction → Save/Edit/Discard |
| **Router-0** | LLM proxy at vt2693-router-0.hf.space/v1, OpenAI-compatible |
| **Telegram offset** | In-memory `update_id + 1` tracking; on crash ~1 batch may be lost |

## Deploy Commands

```bash
# Fresh deploy (phone)
git clone https://github.com/vt2693/bot-0.git ~/hermes-bot
cd ~/hermes-bot && bash setup_android.sh && bash start_android.sh

# Update and restart
cd ~/hermes-bot && git pull origin main && tmux kill-session -t hermes; bash start_android.sh

# View logs
tail -f ~/hermes-bot/logs/bot.log

# Attach to tmux
tmux attach -t hermes

# Re-run setup (preserves existing tokens)
bash setup_android.sh
```