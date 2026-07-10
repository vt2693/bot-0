---
title: Bot 0
emoji: 👁
colorFrom: red
colorTo: indigo
sdk: docker
pinned: false
app_port: 7860
---

# Hermes Agent Bot 0

Android/Termux Telegram bot with:

- Headless Telegram polling (getUpdates)
- 8-provider LLM routing via httpx (no openai SDK)
- Composio MCP tools (Jira, Firecrawl)
- Voice memo → transcription → LLM minutes (Groq/NVIDIA)
- SQLite memory (facts + learned skills)
- Scheduler engine (periodic tasks)
- Inline keyboard menus

## Required secrets

Set in `~/.hermes-tokens.env`:

- `TELEGRAM_BOT_TOKEN`
- `GROQ_API_KEY`
- `ROUTER_0_API_KEY`
- `COMPOSIO_CONSUMER_API_KEY` (for Jira/Firecrawl tools)
- Optional: `JIRA_EPICS` — comma-separated epic keys
- Optional: `AUTO_LEARN=true` to detect reusable skills
- Optional: `BROADCAST_CHAT_ID=-100...` — channel for tool call results

## Android deploy

```bash
pkg install -y git python ffmpeg tmux termux-api
git clone https://github.com/vt2693/bot-0.git hermes-bot
cd hermes-bot
bash setup_android.sh
nano ~/.hermes-tokens.env
bash start_android.sh
tmux attach -t hermes
```

## Files

- `android_bot.py` — main entry point (poll loop)
- `telegram_bot.py` — menus, callbacks, outbox
- `hermes_bridge.py` — LLM bridge (httpx), tool loop
- `config.py` — 8-provider settings
- `composio_mcp.py` — Composio MCP client
- `memory_store.py` — SQLite facts + skills
- `scheduler.py` — periodic task engine
- `tg_voice.py` — download → ffmpeg → Groq transcription
- `deploy_android.ps1` — Windows ADB/SSH deploy script
