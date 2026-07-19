"""Hermes Agent — Android/Termux entry point (headless Telegram bot).

Reuses all existing modules unchanged. getUpdates polling replaces webhook.
Outbound messages delivered directly via urllib to api.telegram.org.
Voice transcribes in-process via local router-0 STT.
"""

import asyncio
import json
import logging
import os
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from config import get_settings
from composio_mcp import ComposioMCP
from hermes_bridge import HermesBridge
from memory_store import MemoryStore
from scheduler import SchedulerEngine
from telegram_bot import TelegramBot
from tg_voice import tg_file_path, download_file, to_wav, transcribe

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("android_bot")


def _get_updates_sync(token: str, offset: int) -> list[dict]:
    """Synchronous getUpdates call (runs in asyncio.to_thread)."""
    url = (
        f"https://api.telegram.org/bot{token}/getUpdates"
        f"?offset={offset}&timeout=30"
        "&allowed_updates=%5B%22message%22,%22callback_query%22%5D"
    )
    with urllib.request.urlopen(url, timeout=35) as resp:
        data = json.loads(resp.read().decode())
    return data.get("result", [])


async def _drain_outbox(tg: TelegramBot) -> None:
    """Background task: drain outbox and deliver directly to Telegram API."""
    while True:
        try:
            items = await tg.drain_outbox()  # async, not to_thread
            if not items:
                await asyncio.sleep(0.5)
                continue
            for item in items:
                ok = await asyncio.to_thread(tg._send_direct, item)
                if not ok:
                    logger.warning(
                        "Direct send failed: %s", item.get("_method", "?")
                    )
                    await asyncio.sleep(2)
                    await asyncio.to_thread(tg._send_direct, item)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("Outbox drain error: %s", e)
            await asyncio.sleep(1)


async def _process_voice(
    tg: TelegramBot, msg: dict, work_dir: Path
) -> str:
    """Download Telegram voice, transcribe, return transcript.

    Sends progress messages to the chat as steps complete.
    """
    chat_id = msg["chat"]["id"]
    file_id = msg["voice"]["file_id"]
    duration = msg["voice"].get("duration", 0)

    tg._send_message(chat_id, f"\U0001f3a4 Voice ({duration}s) — downloading...")
    try:
        path = tg_file_path(tg.token, file_id)
        src = work_dir / (
            "voice_" + file_id.replace(":", "_") + Path(path).suffix
        )
        download_file(tg.token, path, src)
    except Exception as e:
        tg._send_message(chat_id, f"❌ Download failed: {e}")
        return ""

    tg._send_message(chat_id, "\U0001f3a4 Converting to WAV...")
    try:
        wav = to_wav(src)
    except Exception as e:
        tg._send_message(chat_id, f"❌ Audio conversion failed: {e}")
        return ""

    tg._send_message(chat_id, "\U0001f3a4 Transcribing...")
    try:
        text = transcribe(wav)
    except Exception as e:
        tg._send_message(chat_id, f"❌ Transcription failed: {e}")
        return ""

    # Clean up temp files
    try:
        src.unlink(missing_ok=True)
        wav.unlink(missing_ok=True)
    except Exception:
        pass

    return text


async def _poll_loop(tg: TelegramBot, work_dir: Path) -> None:
    """Poll getUpdates, process voice inline, feed into enqueue_update."""
    offset = 0
    while True:
        try:
            updates = await asyncio.wait_for(
                asyncio.to_thread(_get_updates_sync, tg.token, offset),
                timeout=32,
            )
            if not updates:
                await asyncio.sleep(1)
                continue
            for update in updates:
                msg = update.get("message") or {}
                if msg.get("voice"):
                    chat_id = msg.get("chat", {}).get("id")
                    text = await _process_voice(tg, msg, work_dir)
                    if text and chat_id:
                        tg._send_message(
                            chat_id, f"\U0001f4dd Transcript: {text}"
                        )
                        # Re-route as text so LLM processes it
                        msg["text"] = text
                        msg.pop("voice", None)
                tg.enqueue_update(update)
                offset = update["update_id"] + 1
        except asyncio.CancelledError:
            break
        except (asyncio.TimeoutError, TimeoutError):
            continue
        except Exception as e:
            logger.error("Poll loop error: %s", e)
            await asyncio.sleep(2)


async def main() -> None:
    """Initialize all components and start the poll loop."""
    s = get_settings()

    if not s.TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN is required", flush=True)
        sys.exit(1)

    # Initialize all components
    composio = ComposioMCP(s.COMPOSIO_CONSUMER_API_KEY or "")
    db_path = s.MEMORY_DB_PATH or "/sdcard/Download/hermes_memory.db"
    store = MemoryStore(db_path)
    bridge = HermesBridge(s, composio=composio)
    bridge.memory_store = store
    bridge.initialize()

    tg = TelegramBot(
        s.TELEGRAM_BOT_TOKEN,
        lambda msg, hist, scope="global": bridge.chat_with_memory(
            msg, hist, scope
        ),
        bridge=bridge,
        allowed_users=s.TELEGRAM_ALLOWED_USERS,
    )

    if composio.configured:
        logger.info("Initializing Composio...")
        await composio.initialize_async()

    # Manual init (skip webhook config — not needed for polling mode)
    # Clear any stale webhook so getUpdates works (retry once)
    for attempt in range(2):
        try:
            req = urllib.request.Request(
                f"https://api.telegram.org/bot{s.TELEGRAM_BOT_TOKEN}/deleteWebhook",
                data=b'{"drop_pending_updates":true}',
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=10)
            break
        except Exception:
            if attempt == 0:
                await asyncio.sleep(2)
            else:
                logger.warning("deleteWebhook failed after 2 attempts")

    # Self-test: verify token via getMe
    try:
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{s.TELEGRAM_BOT_TOKEN}/getMe"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            me = json.loads(resp.read().decode())
            logger.info("Authenticated as @%s", me.get("result", {}).get("username", "?"))
    except Exception as e:
        logger.error("Token validation failed (getMe): %s", e)

    tg._initialized = True
    tg._start_time = time.time()
    tg.configure_commands()

    # Start scheduler
    tg.scheduler = SchedulerEngine(db_path, bridge, tg, store)
    tg.scheduler.start()

    # Start queue worker (pulls from enqueue_update)
    worker_task = asyncio.create_task(tg.process_queue_worker())

    # Start outbox drain (delivers to api.telegram.org)
    outbox_task = asyncio.create_task(_drain_outbox(tg))

    # Send startup notification
    broadcast_id = os.getenv("BROADCAST_CHAT_ID", "")
    if broadcast_id and broadcast_id.isdigit():
        tg._send_message(
            int(broadcast_id),
            "✅ Hermes Agent started on Android",
        )

    # Work dir for voice temp files
    work_dir = Path(os.getenv("WORK_DIR", tempfile.gettempdir()))
    work_dir.mkdir(parents=True, exist_ok=True)

    # Log startup configuration
    allowed = s.TELEGRAM_ALLOWED_USERS or "all users"
    logger.info(
        "Bot started: provider=%s model=%s allowed=%s composio=%s",
        bridge.status().get("provider", "?"),
        bridge.status().get("model", "?"),
        allowed,
        composio.configured,
    )

    try:
        await _poll_loop(tg, work_dir)
    finally:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        outbox_task.cancel()
        try:
            await outbox_task
        except asyncio.CancelledError:
            pass
        if tg.scheduler:
            await tg.scheduler.stop()
        await composio.close()
        try:
            store.close()
        except Exception:
            pass  # _backup_to_hub may fail without storage token on Android


if __name__ == "__main__":
    asyncio.run(main())
