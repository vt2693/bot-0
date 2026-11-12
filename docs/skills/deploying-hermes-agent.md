---
name: deploying-hermes-agent
description: >-
  Deploy Hermes Agent to Android/Termux (headless Telegram bot via getUpdates polling).
  3-provider LLM config with router_0, SchedulerEngine, MemoryStore (SQLite),
  Composio MCP tools, TTS and in-process voice transcription via local router-0.
  Retry + provider failover on upstream capacity exhaustion.
  Confidence: 100%
---

# Deploying Hermes Agent to Android (Termux)

## Purpose

Run the Hermes Agent on an Android phone via Termux — a headless Telegram bot with getUpdates polling. Supports multi-provider LLM (router_0, opencode_zen, openrouter), Composio MCP tools (including Firecrawl scrape/crawl/search and Jira), voice memo transcription (local router-0 STT), text-to-speech (TTS, local router-0), MemoryStore (SQLite), SchedulerEngine for periodic tasks, and inline keyboard menus.

## Supported Environments

- **Android phone (Termux)** — primary deployment target
- Local development machine (Windows/Linux/macOS) for testing

## Final Verified Deployment State

Verified 2026-11-12:

- Source of truth: `main` on GitHub; local checkout and `origin/main` synchronized at commit `9f3cf75`.
- Termux deployment: `~/hermes-bot`, managed by `tmux` session `hermes` and `start_android.sh` auto-restart loop.
- Remote administration: Ed25519 SSH key authentication on Termux port `8022`; password-free login verified.
- Runtime: `android_bot.py` running; Telegram `getMe` authentication passed; `SchedulerEngine` polling every 30 seconds; Router-0 provider returned successful test responses.
- Access control: `TELEGRAM_ALLOWED_USERS` contains numeric Telegram user IDs separated by spaces; text and callback authorization use sender IDs, not usernames. Callback sender checks run before acknowledgement or action routing.
- Memory scope policy: private chats use `user:<sender_id>`; group and supergroup chats use `chat:<chat_id>`. Updates without valid sender/chat identity are rejected.
- Scheduler ownership: jobs use per-chat scope; remove, pause, resume, and run-now require owning `chat_id`. Legacy `sched_global` rows migrate to the stored chat scope at startup.
- Scheduler reliability: failed provider calls use failure-time retry backoff; no new `UnboundLocalError` after restart.
- Health check: inspect `tmux ls`, Python process, and recent `Authenticated`, `Bot started`, `Scheduler started`, `Outbox drained`, and error log lines.
- Deployment safety: preserve Termux local work with a backup branch and `git stash -u` before merging `origin/main`; do not use `git reset --hard` without explicit approval.

### Non-Goals

- Remote memory persistence — SQLite-only, no cloud sync

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
    │  ── transcribe│           │(timers+30s) │
    │               │           └─────────────┘
    │  tg_tts.py    │
    │  ── synthesize│
    │  ── to_opus ──┤──▶ sendVoice (httpx multipart POST to api.telegram.org)
    └───────────────┘
```

**Key insight:** Android bot uses **direct** Telegram API calls. `android_bot.py` long-polls `getUpdates` for inbound messages and calls `api.telegram.org` directly for outbound via `_send_direct()`. No webhook.

PDFs sent to the chat are auto-analyzed: `_handle_document()` downloads the file, extracts text via `pdf_doc.py` (pypdf), sends a summary, then loads the text into scope-keyed `_pdf_context` so follow-up messages become PDF Q&A. Private-chat context uses `user:<sender_id>`; group context uses `chat:<chat_id>`. `/pdf_stop` (or the inline "Exit PDF Q&A" button) clears that context and returns to normal chat.

Voice is processed **in-process**: download → ffmpeg (16kHz WAV) → router-0 STT (groq/whisper-large-v3). TTS: text → `synthesize()` (MP3) → `to_opus()` (OggOpus) → `sendVoice`.

## Files

| File | Purpose |
|------|---------|
| `android_bot.py` | Main entry point — getUpdates poll loop, outbox drain, voice handling |
| `telegram_bot.py` | Queue, outbox, inline menus, callback routing, command handlers, TTS toggle |
| `hermes_bridge.py` | Multi-provider LLM bridge via httpx (no openai SDK), tool loop, memory injection |
| `config.py` | Settings from env vars, 3-provider auto-detection |
| `composio_mcp.py` | Composio MCP client (HTTP JSON-RPC, workbench for Jira tools) |
| `memory_store.py` | SQLite fact + skill store (SQLite-only on Android) |
| `scheduler.py` | SchedulerEngine (event-driven dispatch + 30s poll backstop) |
| `tg_voice.py` | Voice helper: download, ffmpeg, router-0 STT transcription |
| `tg_tts.py` | TTS helper: synthesize via router-0 (google-tts/en), ffmpeg to OggOpus |
| `pdf_doc.py` | PDF helpers: detect, download, extract text via pypdf (for PDF auto-analyze) |
| `setup_android.sh` | One-shot setup: pkg install, pip deps, token prompts, ROUTER_0_AUDIO_URL |
| `start_android.sh` | tmux launcher with auto-restart, dep check, wake-lock |
| `deploy_android.ps1` | Windows script: ADB push or SSH/rsync to phone (non-interactive) |
| `requirements.txt` | pip deps list (for reference; phone uses `pip install httpx` directly) |
| `.hermes-tokens.env.example` | Environment variable template for reference |

## Confidence: 100%

All components validated end-to-end on Android/Termux with Python 3.14. Voice, TTS, memory, scheduler, Jira, menus, provider switching all verified live.

### Architecture & deployment
Confidence: 100% — Validated end-to-end with live Telegram message delivery. Headless polling, no web server needed.

### config.py provider logic
Confidence: 100% — 3 provider names including `router_0`. Provider auto-detection order: PROVIDER env → `router_0` → `opencode_zen` → `openrouter`. Settings immutable, cached via `@lru_cache()`.

### Provider fallback chain
Confidence: 100% — Transient provider errors (server_error, upstream 5xx, resource exhaustion, rate limit) are classified and retried. Capacity-exhaustion class uses `LLM_RETRY_ATTEMPTS` attempts (default 3, configurable) with `2**attempt` backoff (1/2/4s per capacity exhaustion, or 1.5x for network flakiness). Each attempt has a per-call timeout of `LLM_TIMEOUT` (default 60s, configurable). On exhaustion beyond retries, the bridge fails over to the next configured provider with an announced ⚠️ notice (provider restored next turn); hard client errors (auth, bad request) fail fast. `chat()` re-raises provider errors (logs trace first) so the Telegram layer renders a clean message — no raw API dump to the user.

### Provider switching (/model + inline menu)
Confidence: 100% — Telegram `/model` command and inline model-switch menu (System → Switch Model → `ac:model:*` callback routing). Menu dynamically shows ✅ on active model, ⭐ on provider default.

### Router-0 provider
Confidence: 100% — Auto-detected by API key or base URL. No key required (passes `""` to httpx). Default model: `combo-medium`. Default base: `http://localhost:20128/v1`. Model-switch menu options include `combo-high`, `combo-medium`, `combo-low`, `combo-xlow`, and `combo-xxlow` (routed via `ac:model:combo-*`).

### Telegram bot + polling
Confidence: 100% — Direct Telegram API calls via `urllib`. getUpdates long-poll (30s timeout). Outbound via `_send_direct()` mapping `_TELEGRAM_PATHS`. Outbox drain background task (1 retry). 8 slash commands registered: `/start`, `/menu`, `/help`, `/model`, `/improve`, `/secrets`, `/schedule`, `/pdf_stop`. Inline keyboard menu (11 menus: Main, Web, Memory, Chat, Voice, Skills, System, Model, Schedule, Jira, TTS Model). Callback routing with `mn:*`, `ac:*`, `ac:model:*`, `ac:tts_model:*`, `ac:schedule_*`, `ac:skill_*`, `ac:jira_task:*`, `ac:jira_show:*`, `ac:jira_run:*`, `ac:tts_toggle`, `ac:pdf_stop` prefixes. Per-chat history: 1000 messages as `[{role, content}]`.

### In-process voice (STT)
Confidence: 100% — Voice memo detected in poll loop → download via getFile API → ffmpeg (16kHz mono WAV) → router-0 STT (groq/whisper-large-v3). No separate voice process needed.

### Text-to-Speech (TTS)
Confidence: 100% — Toggleable per resolved Telegram scope from Voice & Minutes menu (`ac:tts_toggle`). State stored in MemoryStore as `tts_enabled=true|false` under `user:<sender_id>` for private chats or `chat:<chat_id>` for groups. TTS model switchable from sub-menu (`mn:tts_model` → `ac:tts_model:*`), stored as `tts_model=<name>` under same scope with default `edge-tts/en-US-AndrewMultilingualNeural`. Runtime and startup restore use scope keys, preventing cross-user/group leakage. On each text response, background task: `tg_tts.synthesize()` → router-0 TTS (MP3) → `tg_tts.to_opus()` (ffmpeg pipe to OggOpus) → `_send_voice_direct()` (httpx multipart POST to `api.telegram.org/bot<token>/sendVoice`). 3 retries with backoff. Long responses split at sentence boundaries into multiple voice messages (~1200 chars per chunk, ~80s audio each) with 1s gap. Text replies similarly split at sentence boundaries into multiple messages (4096 chars max per message, up to 25 messages). Defaults off.

### MemoryStore (LLM-expanded LIKE + SQLite)
Confidence: 100% — Fact search via keyword LIKE on raw message words **plus LLM query-expansion terms** (`get_relevant(extra_terms=...)`; `_expand_query` runs a cheap temp-0 `chat()` call per message, degrades to raw keywords on any failure). **Fast-path optimization:** trivial chat messages (≤10 chars and ≤2 words, no scheduling/memory/tool keywords) skip query expansion entirely to reduce latency. Recent-facts fallback on empty hits. No FTS5, no HRR, no numpy, no vector search. Learned skills table with title/problem/procedure/lifecycle. SQLite-only — no remote sync. Confidence scoring (trust_score for facts, confidence_score for skills) is evaluated by the LLM at insertion time and used in retrieval ordering (confidence DESC, access_count DESC, created_at DESC).

### Composio MCP integration
Confidence: 100% — HTTP JSON-RPC client with initialize → tools/list → tools/call flow. Jira tools accessed via `COMPOSIO_REMOTE_WORKBENCH` + `run_composio_tool()` (not direct `tools/call` RPC). Cold-start retry pattern.

### SchedulerEngine
Confidence: 100% — Event-driven dispatch: per-job timer map wakes a dispatcher task at the earliest `next_run_at` so due jobs start promptly; the 30s async poll loop remains as catch-up/cleanup backstop. SQLite persistence. NL+structured `/schedule` parsing with interval/time-target support. 5-min confirmation TTL. 3-error auto-pause. Once/daily/interval modes. `catch_up` skips once-mode jobs (interval=0 guard). **Run Now** (`⚡ Run Now` button on each job row, `ac:schedule_run:*`) fires a job immediately via `run_now()` → `_spawn_job(job, manual=True)`; manual runs update `last_run_at`/`last_result` but leave `next_run_at` (and thus the schedule) untouched, and `_spawn_job` is the single guard against duplicate concurrent executions.

## Inputs (secrets)

| Input | Required | Source | Notes |
|-------|----------|--------|-------|
| `TELEGRAM_BOT_TOKEN` | Yes | BotFather | Bot authentication |
| `ROUTER_0_API_KEY` | No | Router-0 dashboard | LLM proxy + STT/TTS (empty OK, passes `""` to httpx) |
| `ROUTER_0_BASE_URL` | No | — | Router-0 LLM base URL (default `http://localhost:20128/v1`) |
| `ROUTER_0_AUDIO_URL` | No | — | Router-0 audio base URL for TTS/STT (default none; set to e.g. `http://localhost:20128/v1`) |
| `TELEGRAM_ALLOWED_USERS` | No | — | Comma- or space-separated numeric Telegram user IDs to restrict access; checked against `message.from.id` and `callback_query.from.id` |
| `COMPOSIO_CONSUMER_API_KEY` | For tools | Composio dashboard | Jira, Firecrawl, etc. |
| `OPENCODE_ZEN_API_KEY` | Optional | OpenCode | Alternative LLM provider |
| `OPENROUTER_API_KEY` | Optional | OpenRouter | Alternative LLM provider |
| `JIRA_EPICS` | For Jira menu | Jira | Comma-separated epic keys (e.g. PROJ-123,PROJ-456) |

## Environment Variables

Set in `$HOME/.hermes-tokens.env` (loaded by `start_android.sh`). Config module reads from `os.getenv()` at init. Defaults shown below.

| Variable | Default | Required | Purpose |
|----------|---------|----------|---------|
| `TELEGRAM_BOT_TOKEN` | — | Yes | Telegram bot auth |
| `TELEGRAM_ALLOWED_USERS` | `""` | No | Restrict to specific user IDs |
| `PROVIDER` | *auto-detect* | No | Override LLM provider |
| `ROUTER_0_API_KEY` | — | Yes | Router-0 LLM provider |
| `ROUTER_0_MODEL` | `combo-medium` | No | Router-0 model name |
| `ROUTER_0_BASE_URL` | `http://localhost:20128/v1` | No | Router-0 LLM base URL |
| `ROUTER_0_AUDIO_URL` | — | No | Router-0 audio base URL for TTS/STT (e.g. `http://localhost:20128/v1`) |
| `TTS_URL` | from `ROUTER_0_AUDIO_URL` | No | Override full TTS endpoint URL |
| `STT_URL` | from `ROUTER_0_AUDIO_URL` | No | Override full STT endpoint URL (in tg_voice.py, not config.py) |
| `TTS_MODEL` | `edge-tts/en-US-AndrewMultilingualNeural` | No | TTS model name for router-0 |
| `OPENCODE_ZEN_API_KEY` | — | No | OpenCode Zen LLM |
| `OPENCODE_ZEN_MODEL` | `deepseek-v4-flash-free` | No | OpenCode Zen model |
| `OPENCODE_ZEN_BASE_URL` | `https://opencode.ai/zen/v1` | No | OpenCode Zen base URL |
| `OPENROUTER_API_KEY` | — | No | OpenRouter LLM |
| `OPENROUTER_MODEL` | `openrouter/auto` | No | OpenRouter model |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | No | OpenRouter base URL |
| `COMPOSIO_CONSUMER_API_KEY` | — | No | Composio MCP auth |
| `COMPOSIO_APPS` | `""` | No | Comma-separated app slugs |
| `JIRA_EPICS` | — | No | Comma-separated Jira epic keys |
| `MEMORY_ENABLED` | `true` | No | Enable memory |
| `MEMORY_AUTO_EXTRACT` | `true` | No | Auto-extract facts from conversations |
| `AUTO_LEARN` | `true` | No | Detect reusable procedures and ask before saving |
| `MEMORY_RESTORE_ON_STARTUP` | `false` | No | Restore memory from SQLite on startup |
| `MEMORY_DB_PATH` | *see* | No | SQLite path (default: `$HOME/hermes_memory.db` on Android) |
| `MEMORY_API_KEY` | — | No | Legacy; kept for compat (no-op on Android) |
| `TOOL_LOOP_MAX_ROUNDS` | `1000` | No | Max LLM tool-call rounds |
| `LLM_TIMEOUT` | `60` | No | Per-LLM-call timeout in seconds |
| `LLM_RETRY_ATTEMPTS` | `3` | No | Number of retries for transient LLM errors (capacity exhaustion, 5xx, rate limit) |
| `BROADCAST_CHAT_ID` | — | No | Channel/group chat_id to broadcast tool call results |
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

### SSH Key Setup (recommended for remote deployment)

Use an Ed25519 key instead of embedding the Termux password in scripts or command arguments.

On the deployment machine, create a key if one does not exist:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -C "hermes-termux"
```

Install the public key on Termux through one interactive password-authenticated session:

```bash
cat ~/.ssh/id_ed25519.pub | ssh -p 8022 u0_a296@PHONE_IP \\
  'umask 077; mkdir -p ~/.ssh; cat >> ~/.ssh/authorized_keys; sort -u ~/.ssh/authorized_keys -o ~/.ssh/authorized_keys; chmod 700 ~/.ssh; chmod 600 ~/.ssh/authorized_keys'
```

Verify key-only login. Replace `PHONE_IP` with phone address; never place password in command text:

```bash
ssh -o PreferredAuthentications=publickey \\
  -o PasswordAuthentication=no \\
  -p 8022 u0_a296@PHONE_IP 'printf "key login works\\n"'
```

Optional `~/.ssh/config` entry:

```sshconfig
Host hermes-termux
    HostName PHONE_IP
    Port 8022
    User u0_a296
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes
```

Then use:

```bash
ssh hermes-termux
```

Keep `~/.ssh/id_ed25519` private. Share only `~/.ssh/id_ed25519.pub`. Rotate the Termux password if it was exposed in chat, shell history, process arguments, or logs.

### Step 2: Setup Script (setup_android.sh)

- Installs: `python`, `ffmpeg`, `tmux`, `termux-api`, `git`, `binutils`
- Installs: `httpx` via pip (no openai SDK needed — bot uses direct httpx calls)
- Verifies: `python -c "import httpx"`
- Prompts for 6 configs + 2 optional configs (TELEGRAM_ALLOWED_USERS, JIRA_EPICS) interactively with existing-value defaults: TELEGRAM_BOT_TOKEN, ROUTER_0_API_KEY, ROUTER_0_BASE_URL, ROUTER_0_AUDIO_URL, COMPOSIO_CONSUMER_API_KEY, OPENCODE_ZEN_API_KEY
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
python -c "import sys, importlib.util; pkgs=['httpx']; missing=[...]; ..." || exit 1

termux-wake-lock || true
tmux has-session -t hermes 2>/dev/null && echo "Killing existing session..." && tmux kill-session -t hermes
tmux new-session -d -s hermes -n bot \
  "while true; do python -u android_bot.py 2>&1 | tee -a logs/bot.log; sleep 2; done"
echo "Hermes bot started. Attach: tmux attach -t hermes"
```

### Step 4: Android Bot Entry Point (android_bot.py)

Main asyncio entry point. Key sections:

**Poll loop:** `_poll_loop(tg, work_dir)` — infinite loop calling `getUpdates` with 30s long-poll timeout via `asyncio.to_thread`. Voice messages detected in the loop, processed inline (download → ffmpeg → transcribe), then re-routed as text through the normal queue.

**Outbox drain:** `_drain_outbox(tg)` — background task draining `tg.outbox` and delivering via `_send_direct()` (3 attempts with 1.5x backoff inside `_send_direct`).

**Startup sequence:**
1. Initialize ComposioMCP, MemoryStore, HermesBridge, TelegramBot
2. Delete stale webhook (`deleteWebhook` — ensures getUpdates works)
3. Self-test via `getMe` (verifies token)
4. Start queue worker, outbox drain, scheduler
5. Enter poll loop

**Shutdown:** Cancels worker/outbox tasks, stops scheduler, closes composio, closes store.

### Step 5: LLM Bridge (hermes_bridge.py)

3-provider LLM bridge using **direct httpx calls** (no openai SDK). Key methods:

- `_call_llm()` — sends POST to `/chat/completions` with `stream: False`, handles tool calls in loop up to `TOOL_LOOP_MAX_ROUNDS`. Classifies provider errors: transient (server_error, ResourceExhausted, 5xx, rate limit) retried with escalating backoff; capacity exhaustion beyond retries fails over to the next configured provider with an announced notice. Non-transient (auth/bad request) fail fast.
- `chat_with_memory()` — LLM query expansion (`_expand_query`: lightweight `chat()` call with `system_override`, temp 0, no tools → 3-6 search terms). **Fast-path:** simple messages (≤10 chars and ≤2 words) skip expansion to reduce per-message latency. Retrieves relevant facts + skills, injects into system prompt, calls LLM with `extract_facts` tool, detects skills
- `_build_messages()` — constructs message list from history (dict or tuple format), injected skills/facts
- `_detect_skill()` — heuristic gate + constrained JSON LLM extraction for learned skills
- `_execute_tool()` — calls `ComposioMCP.call_tool_sync()` (sync `httpx.Client`, no event loop needed)

3 provider auto-detection order: PROVIDER env → `router_0` → `opencode_zen` → `openrouter`.

### Step 6: Telegram Bot (telegram_bot.py)

- **Queue:** Thread-safe list. `enqueue_update()` adds, `process_queue_worker()` pops and calls `process_update()`.
- **Outbox:** Thread-safe list. Methods write `{"_method": "sendMessage", ...}`. `drain_outbox()` returns and clears.
- **Inline menus:** `MENUS` dict with 11 menus. Callback routing via `mn:*` (menu nav), `ac:*` (action handlers).
- **Commands (8):** `/start`, `/menu`, `/help`, `/model`, `/improve`, `/secrets`, `/schedule`, `/pdf_stop`.
- **PDF auto-analyze:** Documents with a PDF mime/name trigger `_handle_document()` — download → pypdf text extraction → summary via bridge → scope-keyed `_pdf_context`. Subsequent non-command messages route through PDF Q&A (strict "answer only from the document" system prompt). `/pdf_stop` or the inline **❌ Exit PDF Q&A** button (`ac:pdf_stop`) clears the resolved scope context; `/start` also clears the chat's context.
- **Skills:** `/improve` — list/search/detail/edit/delete skills. Auto-detect via `_detect_skill()` + Save/Edit/Discard confirmation.
- **Schedule — two entry paths to the same scheduler pipeline:**
  - **Manual:** `/schedule add <text>` routes to `parse_schedule()`. Subcommands: `add`, `list`, `remove <id>`, `pause <id>`, `resume <id>`; bare `/schedule` opens the Schedule menu.
  - **Auto-detect:** Plain chat messages matching an action verb + time expression are intercepted in `_handle_message()` before LLM processing. Verb group: `check|scan|summarize|monitor|watch|fetch|poll|read|get|review|report|remind`. Time patterns: `every N`, `in N min/hour/day/sec`, `at HH:MM am/pm`. Non-matches fall through to normal chat.
- **NL→JSON parsing** in `parse_schedule()`: constrained LLM call with `system_override=` (clean prompt, no personality/memory/skills injected), 3-attempt retry loop with error feedback, epoch validation, `temperature=0`. Returns one of three shapes: `{"interval_minutes": N, "prompt": "..."}`, `{"absolute_epoch": UnixTS, "prompt": "..."}`, or `{"error": "reason"}`. Full CRUD via inline buttons, plus **⚡ Run Now** (immediate manual run — updates `last_run`, keeps `next_run_at` intact). Supports interval, absolute-time (Run Once / Daily), and once/daily modes.
- **Jira:** `mn:jira` → `ac:jira_open_tasks` → `COMPOSIO_REMOTE_WORKBENCH` with `run_composio_tool("JIRA_SEARCH_FOR_ISSUES_USING_JQL_GET", ...)`. Open tasks filtered to `status IN ("To Do","In Progress")`. Subtask rows: `[🔵 key: summary] [▶️ Run]`. Tapping subtask left button (`ac:jira_show:*`) fetches full issue via `JIRA_GET_ISSUE` and renders description as plain text (ADF → text converter via `json.loads` + `ast.literal_eval` fallback). `ac:jira_run:*` sends description as LLM prompt with `_skill_detected` JSON unwrap. Subtask list filtered to open statuses only (no Done items).
- **TTS:** Scope-aware toggle via `ac:tts_toggle`. `_tts_chats` and `_tts_scopes` track runtime state; MemoryStore persists `tts_enabled=true|false` under resolved scope. Models use the same scope key. After each text response, background task fires: `_send_tts_async()` → `tg_tts.synthesize()` (MP3) → `tg_tts.to_opus()` (OggOpus) → `_send_voice_direct()` (httpx multipart POST to api.telegram.org). 3 retries with backoff. Long responses split at sentence boundaries into multiple voice messages (~1200 chars per chunk, ~80s audio each) with 1s gap. Text replies similarly split at sentence boundaries into multiple messages (4096 chars max per message, up to 25 messages). Defaults off.

### Step 7: Memory Store (memory_store.py)

SQLite-backed fact + skill store. SQLite-only on Android.

- **Facts:** `facts` table with LIKE search, trust_score (+0.05/-0.10), cleanup_low_trust (< 0.2). Retrieval is keyword `LIKE` on raw message words plus LLM-expanded terms (`get_relevant(extra_terms=...)`, word cap 10); recent-facts fallback on empty hits.
- **Skills:** `skills` table with title/problem/procedure/failure_pattern/status lifecycle (unverified → active → inactive).
- **Scheduled jobs:** `scheduled_jobs` table co-located for SchedulerEngine. New rows use per-chat ownership scope; legacy `sched_global` rows migrate from stored `chat_id` at startup. CRUD controls require owning `chat_id`.

### Step 8: Scheduler (scheduler.py)

Event-driven dispatch: per-job timer map (`_timers`), dispatcher task wakes at the earliest `next_run_at` via `asyncio.wait_for` and spawns due jobs promptly; 30s async poll loop stays as catch-up/cleanup backstop. Timers re-armed after each run by mode (daily/interval re-schedules, once/3-error clears). Checks `scheduled_jobs.next_run_at ≤ now`. 3 consecutive errors → auto-pause with notification. Cold-boot catch-up (skip >2 intervals behind). Max 20 jobs/chat. Failure handling captures `now` inside the exception path before calculating retry backoff, so provider timeouts use failure time rather than stale job-start time.

### Step 9: Composio MCP (composio_mcp.py)

HTTP JSON-RPC client. Tools accessed via `initialize` → `tools/list` → `tools/call`. **Jira tools: `tools/call` returns only meta-tools; actual Jira tools accessed via `COMPOSIO_REMOTE_WORKBENCH` + `run_composio_tool()`. Cold-start: first workbench call may return empty; retry once after 2s.

`get_openai_tools()` converts to OpenAI function-calling format (max 64 tools). SSE response parsing. Accept header: `application/json, text/event-stream`.

## Error Recovery

| Signal | Action |
|--------|--------|
| LLM upstream saturation (ResourceExhausted / server_error / 5xx) | Retry `LLM_RETRY_ATTEMPTS` times (default 3) with `2**attempt` backoff, then fail over to next configured provider with ⚠️ notice |
| Non-transient LLM error (auth, bad request, invalid model) | Fail fast — no retry, clean user message |
| LLM call returns streaming (SSE) | Ensure `stream: False` in request body |
| Composio cold start returns empty | Retry once after 2s |
| getUpdates timeout | `asyncio.wait_for` wrapper catches `TimeoutError`, continues loop |
| 3 consecutive scheduler failures | Auto-pause job with user notification |
| Tool loop stalls | Capped at `TOOL_LOOP_MAX_ROUNDS` (default 1000), returns summary |
| Module not found | `start_android.sh` verifies deps before launching |
| Outbox send fails | 3 attempts with 1.5x exponential backoff inside `_send_direct` |
| ffmpeg fails (STT/TTS) | Surfaces stderr with actual error reason (e.g., "library X not found"), user notified, no crash |
| TTS synthesis fails (router-0 down) | Error logged with diagnostics, no voice sent. User still got text reply. |
| Telegram API blocks voice send | Logged warning, text reply delivered via outbox (separate path) |

## Edge Cases Covered

| Case | Handling |
|------|----------|
| Stale webhook from prior deployment | `deleteWebhook` called on startup; startup uses `drop_pending_updates=true`, so pending updates can be discarded |
| Telegram API token invalid | `getMe` self-test at startup logs failure |
| Voice download fails | User notified, no crash |
| ffmpeg fails (STT/TTS) | Error logged with actual stderr (e.g., missing library), no crash, user notified |
| Transcription fail | Router-0 STT error, user notified |
| TTS synthesis fails | Error logged, text reply still sent |
| Telegram API unreachable for voice | `_send_voice_direct` retries 3× and logs |
| Jira tools not configured | Empty JIRA_EPICS → warning message via menu |
| Composio not configured | Menu entry shows "not available" |
| getUpdates queue overflow | Telegram stores 24h of updates; offset tracking prevents duplicates |
| Work dir missing | Created at startup via `mkdir` |

## Verification

After `bash start_android.sh`:

1. Send `/start` to bot → should respond with welcome message
2. Send `/menu` → should show inline keyboard with menus
3. Send text → should get LLM response
4. Send voice memo → should transcribe and reply (requires router-0 STT)
5. Send "remember that I live in Bogor" → should store and recall on later messages
6. Tap Jira → Open Tasks → should show issues (requires JIRA_EPICS + Composio key)
7. Tap Menu → Voice & Minutes → TTS On/Off → toggle on, send text → should reply with text + voice message
8. Send a PDF → should download, extract text, summarize, then answer questions about it; `/pdf_stop` (or the exit button) returns to normal chat
9. Check logs: `tail -20 ~/hermes-bot/logs/bot.log`
10. Check runtime: `tmux ls` and `ps -ef | grep -E "[a]ndroid_bot|[p]ython.*hermes"`.
11. If a user gets `Unauthorized` from an inline button, add the exact numeric `callback_query.from.id` to `TELEGRAM_ALLOWED_USERS`; usernames and guessed IDs do not work. The parser accepts commas or spaces.
12. If provider calls time out, inspect `bot.log` for `httpx.ReadTimeout`; scheduler failure handling uses failure-time backoff and should not raise `UnboundLocalError`.

### Allowlist Troubleshooting

`TELEGRAM_ALLOWED_USERS` accepts numeric IDs separated by spaces or commas. Usernames such as `@example` are not accepted. Incoming text checks `message.from.id`; inline-button callbacks check `callback_query.from.id`. A chat ID copied from another bot or guessed from a username can be wrong.

To discover a new user's exact ID without letting the running poller consume the update:

```bash
cd ~/hermes-bot
tmux kill-session -t hermes 2>/dev/null || true
. "$HOME/.hermes-tokens.env"
TELEGRAM_BOT_TOKEN="$TELEGRAM_BOT_TOKEN" python - <<'PY'
import json
import os
import urllib.parse
import urllib.request

params = urllib.parse.urlencode({
    "timeout": 3,
    "allowed_updates": json.dumps(["message", "callback_query"]),
})
url = "https://api.telegram.org/bot" + os.environ["TELEGRAM_BOT_TOKEN"] + "/getUpdates?" + params
with urllib.request.urlopen(url, timeout=10) as response:
    data = json.loads(response.read().decode())
for update in data.get("result", []):
    message = update.get("message") or {}
    callback = update.get("callback_query") or {}
    sender = message.get("from") or callback.get("from") or {}
    chat = message.get("chat") or (callback.get("message") or {}).get("chat") or {}
    print({
        "update_id": update.get("update_id"),
        "user_id": sender.get("id"),
        "chat_id": chat.get("id"),
        "callback": bool(callback),
    })
PY
```

Add the exact `user_id`, preserving existing IDs, then restart:

```bash
sed -i 's/^export TELEGRAM_ALLOWED_USERS=.*/export TELEGRAM_ALLOWED_USERS="ID1 ID2 NEW_ID"/' "$HOME/.hermes-tokens.env"
chmod 600 "$HOME/.hermes-tokens.env"
bash start_android.sh
grep -E "Authenticated|Bot started|Scheduler started|Outbox drained" logs/bot.log | tail -10
```

If Telegram returns `Bad Request: chat not found`, the ID is not an accessible chat for this bot. The user must open the bot and send `/start` first. If an inline button returns `Unauthorized`, capture `callback_query.from.id`, not only `message.chat.id`.

## Quick Reference

### Startup Flow
```
start_android.sh
  → source .hermes-tokens.env
  → verify httpx
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
| **_send_voice_direct** | `httpx` multipart POST to `api.telegram.org/bot<token>/sendVoice` for voice message upload |
| **Queue** | Thread-safe list in TelegramBot; `process_queue_worker` pops and dispatches |
| **Outbox** | Thread-safe list of `{_method, ...}` dicts; `drain_outbox` returns to caller |
| **`_method` dispatch** | Field in outbox dicts mapping to Telegram API method (sendMessage, etc.) |
| **TELEGRAM_PATHS** | Dict mapping method names to API paths (`sendMessage → /sendMessage`) |
| **MemoryStore** | SQLite-backed fact + skill store; LIKE search on raw + LLM-expanded terms (`extra_terms`), no FTS5, no vector search; SQLite-only on Android |
| **SchedulerEngine** | Event-driven dispatch (per-job timers, prompt wake) + 30s poll backstop, SQLite persistence, 3-error auto-pause |
| **Composio MCP** | HTTP JSON-RPC to connect.composio.dev/mcp; Jira via workbench |
| **COMPOSIO_REMOTE_WORKBENCH** | Code execution tool for Jira access (not direct tools/call RPC) |
| **Learned skills** | SQLite skills table: title/problem/procedure/status lifecycle |
| **Auto-learn** | Detect reusable procedures via heuristic → LLM extraction → Save/Edit/Discard |
| **Router-0** | LLM proxy at configurable `ROUTER_0_BASE_URL`; TTS/STT at configurable `ROUTER_0_AUDIO_URL`, both OpenAI-compatible |
| **Telegram offset** | In-memory `update_id + 1` tracking; on crash ~1 batch may be lost |
| **Memory scope** | Private Telegram chats use `user:<sender_id>`; groups use `chat:<chat_id>` |
| **TTS toggle** | Scope-aware TTS enable/disable state persisted in MemoryStore as `tts_enabled=true\|false` |

## Deploy Commands

```bash
# Fresh deploy (phone)
git clone https://github.com/vt2693/bot-0.git ~/hermes-bot
cd ~/hermes-bot && bash setup_android.sh && bash start_android.sh

# Inspect before update
cd ~/hermes-bot
git status --short --branch
git log --oneline --decorate -5

# Safe update when Termux has local commits or edits
# Keep a recovery branch and stash tracked + untracked files.
backup="pre-main-update-$(date +%Y%m%d-%H%M%S)"
git branch "$backup"
git stash push -u -m "$backup"
git fetch origin main
git merge --no-edit origin/main
git stash pop

# Resolve conflicts before restarting. Generated graphify-out files can use origin/main,
# then run graphify update . if source files changed locally.
git status --short
python -m py_compile android_bot.py telegram_bot.py hermes_bridge.py scheduler.py
bash start_android.sh

# View logs
tail -f ~/hermes-bot/logs/bot.log

# Attach to tmux
tmux attach -t hermes

# Re-run setup (preserves existing tokens)
bash setup_android.sh
```

After restart, verify:

```bash
tmux ls
ps -ef | grep -E "[a]ndroid_bot|[p]ython.*hermes"
grep -E "Authenticated|Bot started|Scheduler started|Outbox drained" logs/bot.log | tail -10
```

Do not use `git reset --hard` during deployment unless local files and commits are backed up and discarded changes are explicitly approved. Never put Telegram or provider secrets in Git commands, SSH arguments, logs, or commit content.
