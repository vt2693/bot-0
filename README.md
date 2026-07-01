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

Docker HF Space wrapper for `hermes-agent` with:

- FastAPI health/API
- Gradio web chat
- Telegram getUpdates polling + outbox relay (external — HF Space can't reach api.telegram.org)
- Android Termux relay scripts
- SQLite memory with HF Hub backup
- Composio MCP client
- Firecrawl scrape/search/crawl via Composio MCP
- voice memo → transcription relay → LLM minutes

## Required Space secrets

Set in HF Space Settings → Secrets:

- `OPENCODE_ZEN_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_USERS`
- `COMPOSIO_CONSUMER_API_KEY`
- Optional: `GROQ_API_KEY` for in-Space chat fallback. Voice relay reads Groq on Android.
- Optional: `PROVIDER=opencode_zen`

## Android relay

Termux:

```bash
pkg update && pkg install -y git python ffmpeg tmux termux-api
git clone https://huggingface.co/spaces/vt2693/bot-0 hermes-relay
cd hermes-relay
bash setup_android.sh
nano ~/.hermes-tokens.env
bash start_android.sh
tmux attach -t hermes
```

Never commit real secrets. `start_android.sh` sources `~/.hermes-tokens.env`.

## Endpoints

- `GET /health`
- `POST /webhook/telegram`
- `GET /api/tg_outbox`
- `POST /api/tg_reconfigure`
- `GET /api/tg_voice_pending`
- `POST /api/tg_voice_result`
- `POST /api/tg_voice_fail`
- `/api/memory/*`
