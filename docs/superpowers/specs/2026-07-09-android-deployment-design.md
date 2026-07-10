# Android (Termux) Deployment for Hermes Agent

## Motivation

HF Space free tier has proven unreliable for running Hermes Agent:
- Scheduler gets stuck at `APP_STARTING`
- No hardware allocation during congestion
- Cannot restart via API — requires UI Factory Restart
- Outbound Telegram API calls are throttled

Moving the entire stack to an Android phone via Termux eliminates these bottlenecks entirely. The phone has always run the relay side anyway — this extends it to run the full server.

## Architecture

```
Phone (Termux)

├── ~/hermes-relay/          (git clone of repo)
│   ├── android_bot.py       NEW — main asyncio entry point
│   ├── config.py            unchanged
│   ├── telegram_bot.py      unchanged
│   ├── hermes_bridge.py     unchanged
│   ├── composio_mcp.py      unchanged
│   ├── memory_store.py      unchanged
│   ├── scheduler.py         unchanged
│   ├── app.py               unused (no web server)
│   ├── healthcheck.py       unused
│   ├── relay.py             unused (direct Telegram calls)
│   ├── voice_relay.py       unused (voice in-process)
│   └── Dockerfile           unused
│
├── .hermes-tokens.env       secrets (existing location)
│
├── tmux session: hermes
│   ├── pane 0: "python -u android_bot.py"
│   └── pane 1: optional for debugging
│
└── termux-wake-lock         keeps CPU alive

┌──────────────────────────────────────────────────────────┐
│                   android_bot.py                          │
│                                                           │
│  ┌──────────────┐    ┌──────────────────┐                 │
│  │ getUpdates    │───▶│ _process_update()│                 │
│  │ (30s poll)    │    │  (existing)       │                 │
│  └──────────────┘    └────────┬─────────┘                 │
│                               │                            │
│          ┌────────────────────┼────────────────────┐       │
│          ▼                    ▼                    ▼       │
│   ┌──────────┐       ┌──────────────┐      ┌──────────┐   │
│   │ Text msg  │       │ CallbackQuery │      │ Voice    │   │
│   │ → bridge  │       │ → MENU_ACTIONS│      │ → trans. │   │
│   │ → LLM     │       │ → routing    │      │ → bridge │   │
│   └──────────┘       └──────────────┘      └──────────┘   │
│                                                           │
│  ┌─────────────────────────────────────────────┐          │
│  │ SchedulerEngine (30s poll, SQLite tasks)    │          │
│  └─────────────────────────────────────────────┘          │
│                                                           │
│  MemoryStore → /sdcard/Download/hermes_memory.db          │
│  (survives restarts)                                      │
└──────────────────────────────────────────────────────────┘
```

**Key insight:** `TelegramBot._process_update()` handles all message types (text, callback, voice, commands) — it was designed for webhook delivery but works identically with `getUpdates` polling. Zero changes needed.

## Changes

### New file: `android_bot.py`

Single asyncio entry point (~90 lines). Main loop:

```python
async def main():
    s = get_settings()
    composio = ComposioMCP(s.COMPOSIO_CONSUMER_API_KEY or "")
    store = MemoryStore(s.MEMORY_DB_PATH or "/sdcard/Download/hermes_memory.db")
    bridge = HermesBridge(s, composio=composio)
    bridge.memory_store = store
    bridge.initialize()
    tg = TelegramBot(s.TELEGRAM_BOT_TOKEN or "",
        lambda msg, hist, scope: bridge.chat_with_memory(msg, hist, scope),
        bridge=bridge, allowed_users=s.TELEGRAM_ALLOWED_USERS)
    if composio.configured:
        await composio.initialize_async()
    await tg.initialize_async()
    tg.scheduler = SchedulerEngine(s.MEMORY_DB_PATH or "...", bridge, tg, store)
    tg.scheduler.start()
    
    offset = 0
    while True:
        updates = await tg._call_tg_api("getUpdates", {
            "offset": offset, "timeout": 30,
            "allowed_updates": ["message", "callback_query"]
        })
        for update in (updates or []):
            msg = update.get("message") or {}
            if msg.get("voice"):
                text = await _process_voice(tg, msg)  # in-process
                tg._send_message(msg["chat"]["id"],
                    f"*Voice ({msg['voice']['duration']}s):* _{text}_\n\n---")
                # Re-route as text for LLM processing
                msg["text"] = text
            tg._process_update(update)
            offset = update["update_id"] + 1
```

### Voice handling: `_process_voice`

Inline in `android_bot.py`. Reuses existing `voice_relay.py` helpers:
1. Telegram `getFile` → download `.oga`
2. `ffmpeg -y -i src -ar 16000 -ac 1 out.wav`
3. Groq Whisper (`whisper-large-v3`) or NVIDIA fallback
4. Returns transcript text

Helpers (download_file, to_wav, transcribe, multipart_transcribe) extracted from `voice_relay.py` into a small shared module `tg_voice.py`. Both `voice_relay.py` (kept for backward compat) and `android_bot.py` import from it.

### Updated: `setup_android.sh`

- `pkg install python ffmpeg tmux termux-api git`
- `pip install openai httpx numpy huggingface_hub`
- Prompts for secrets → saves to `~/.hermes-tokens.env`
- No FastAPI/Gradio in install

### Updated: `start_android.sh`

- `termux-wake-lock`
- Single tmux pane: `python -u android_bot.py` with auto-restart loop

### No changes to existing Python modules

All existing code (`telegram_bot.py`, `hermes_bridge.py`, `composio_mcp.py`, `memory_store.py`, `scheduler.py`, `config.py`) runs as-is.

## Data flow

### Text message
```
getUpdates → _process_update() → TelegramBot._process_message()
→ bridge.chat_with_memory() → LLM → tg._send_message()
```

### Callback query (inline buttons)
```
getUpdates → _process_update() → TelegramBot._handle_callback()
→ MENU_ACTIONS_ASYNC routing → action response
```

### Voice
```
getUpdates → _process_update() → voice detected
→ file download → ffmpeg → Groq whisper → transcript → tg._send_message()
→ re-route transcript as text → LLM
```

### Scheduled task
```
SchedulerEngine (30s poll) → triggers bridge.chat()
→ result → tg._send_message()
```

## Error recovery

| Scenario | Handling |
|----------|----------|
| `getUpdates` fails (network) | Loop retries after 2s sleep |
| LLM call fails | Error message sent to chat (existing behavior) |
| Composio cold-start | Retry once after 2s (existing behavior) |
| Scheduler crash | 3-error auto-pause + notification (existing) |
| Full process crash | `while true; do python -u android_bot.py; sleep 2; done` |
| Phone reboot | `start_android.sh` re-run manually |
| Memory DB corruption | Restore from last HF Hub backup (existing) |
| Telegram API rate limit (429) | Retry-after header handling (existing) |

## Required secrets

| Secret | Source |
|--------|--------|
| `TELEGRAM_BOT_TOKEN` | BotFather |
| `GROQ_API_KEY` | Groq console (voice) |
| `ROUTER_0_API_KEY` | Router-0 proxy |
| `COMPOSIO_CONSUMER_API_KEY` | Composio dashboard (optional) |
| `OPENCODE_ZEN_API_KEY` | OpenCode (optional) |
| `GOOGLE_API_KEY` | Google AI (optional) |
| `ANTHROPIC_API_KEY` | Anthropic (optional) |
| `OPENAI_API_KEY` | OpenAI (optional) |
| `NVIDIA_API_KEY` | NVIDIA (optional, voice fallback) |

## Verification

1. `python -c "import asyncio; from android_bot import main; asyncio.run(main())"` — runs on laptop first
2. Deploy to phone via Termux; `bash start_android.sh`
3. Send `/start` to bot → welcome message
4. Send text → LLM response
5. Send voice → transcript + LLM response
6. Test inline menus (Jira, Memory, etc.)
7. Schedule a task: `/schedule every 5 minutes "say hi"` → fires correctly
8. Tests composio tools run through workbench

## Out of scope

- Gradio web UI (purposefully excluded)
- FastAPI / web endpoints
- HF Space Dockerfile
- relay.py / voice_relay.py (replaced)
- Healthcheck endpoint
- Audio file output of minutes (text-only)

## SKILL.md updates needed

After Android deployment is working, update the SKILL.md to reflect that
the primary deployment target is Android/Termux rather than HF Spaces:
- All bot-0 Space references → Android deployment instructions
- Architecture diagram: remove HF Space box, add phone box
- Confidence statements: adjust for Android-tested status
- Deployment workflow: swap "push to HF Space" for "git push + Termux pull"
