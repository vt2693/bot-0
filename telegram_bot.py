import os
import time
import json
import asyncio
import logging
import threading
import urllib.request
import urllib.error
from typing import Callable

logger = logging.getLogger(__name__)


class TelegramBot:
    def __init__(self, token: str, bridge_chat: Callable, bridge=None, allowed_users: str = ""):
        self.token = token or ""
        self.bridge_chat = bridge_chat
        self.bridge = bridge
        self.allowed_ids = {int(x) for x in allowed_users.replace(",", " ").split() if x.isdigit()}
        self._initialized = False
        self._start_time = 0.0
        self._queue: list[dict] = []
        self._queue_lock = threading.Lock()
        self._queue_processed = 0
        self._queue_error = ""
        self.outbox: list[dict] = []
        self._outbox_lock = threading.Lock()
        self._chat_history: dict[str, list] = {}
        self._history_max = 1000
        self._voice_queue: list[dict] = []
        self._voice_lock = threading.Lock()
        self._menu_msg_id: dict[int, int] = {}  # chat_id -> last menu message_id
        self._sent_count = 0  # messages drained by outbox
        self._sent_error = ""
        self.scheduler = None
        self._pending_schedule: dict[str, dict] = {}
        # Inbound polling (bypass webhook, avoid HF cold-boot issue)
        self._use_polling = os.getenv("TELEGRAM_POLLING", "true").lower() in ("true", "1", "yes")
        self._poll_offset = 0

    @property
    def configured(self) -> bool:
        return bool(self.token)

    async def initialize_async(self) -> bool:
        if not self.token:
            return False
        self._initialized = True
        self._start_time = time.time()
        self.configure_commands()
        if not self._use_polling:
            self.enqueue_webhook()
        else:
            # Delete webhook so Telegram queues updates for getUpdates
            self.enqueue_config("deleteWebhook", {"drop_pending_updates": True})
        return True

    def enqueue_webhook(self) -> None:
        """Re-enqueue webhook config (callable from /reconfigure)."""
        self.enqueue_config("setWebhook", {"url": os.getenv("TELEGRAM_WEBHOOK_URL", os.getenv("SPACE_URL", "https://vt2693-bot-0.hf.space") + "/webhook/telegram"), "allowed_updates": ["message", "edited_message", "callback_query"]})

    def enqueue_config(self, method: str, payload: dict) -> None:
        item = {"_method": method, **payload}
        with self._outbox_lock:
            self.outbox.append(item)

    def configure_commands(self) -> None:
        cmds = [
            {"command": "start", "description": "Welcome"},
            {"command": "menu", "description": "Interactive menu"},
            {"command": "help", "description": "Help"},
            {"command": "model", "description": "List/switch provider"},
            {"command": "improve", "description": "Extract skills from conversation"},
            {"command": "secrets", "description": "Configured providers"},
            {"command": "restart", "description": "Restart instructions"},
            {"command": "reconfigure", "description": "Re-enqueue webhook"},
            {"command": "schedule", "description": "Manage scheduled tasks"},
        ]
        self.enqueue_config("setMyCommands", {"commands": cmds})
        # Do NOT call setChatMenuButton — let Telegram use its own default
        # which shows the burger ☰. Explicitly setting type: "default" after
        # previously setting type: "commands" doesn't restore the burger.

    def enqueue_update(self, update: dict) -> None:
        with self._queue_lock:
            self._queue.append(update)
            if len(self._queue) > 100:
                self._queue.pop(0)

    async def process_queue_worker(self) -> None:
        while self._initialized:
            item = None
            with self._queue_lock:
                if self._queue:
                    item = self._queue.pop(0)
            if not item:
                await asyncio.sleep(0.5)
                continue
            try:
                self._queue_processed += 1
                await self.process_update(item)
            except Exception as e:
                self._queue_error = str(e)
                logger.exception("Telegram queue error")

    async def process_update(self, update: dict) -> None:
        cb = update.get("callback_query")
        if cb:
            await self._handle_callback(cb)
            return
        msg = update.get("message") or update.get("edited_message") or {}
        user_id = msg.get("from", {}).get("id")
        chat_id = msg.get("chat", {}).get("id")
        if not chat_id or (self.allowed_ids and user_id not in self.allowed_ids):
            return
        if msg.get("voice"):
            v = msg["voice"]
            with self._voice_lock:
                self._voice_queue.append({"chat_id": chat_id, "file_id": v.get("file_id"), "duration_s": v.get("duration", 0), "timestamp": time.time()})
            self._send_message(chat_id, "Voice memo received -- transcribing...")
            return
        text = msg.get("text") or ""
        if text.startswith("/"):
            await self._handle_command(chat_id, text)
        elif text:
            await self._handle_message(chat_id, text)

    async def _handle_command(self, chat_id: int, text: str) -> None:
        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""
        if cmd == "/start":
            self._chat_history.pop(str(chat_id), None)
            self._send_message(chat_id, "Hello -- Hermes Agent online. Send text or voice. Use /menu for the interactive menu.")
        elif cmd == "/menu":
            self._menu_msg_id.pop(chat_id, None)  # fresh send, never edit
            await self._show_menu(chat_id, "main")
        elif cmd == "/help":
            self._send_message(chat_id, "/start /menu /model /secrets /restart. Ask normally to chat.")
        elif cmd == "/model":
            if not self.bridge:
                self._send_message(chat_id, "Bridge unavailable")
                return
            if arg:
                self._send_message(chat_id, str(self.bridge.switch_provider(arg)))
            else:
                self._send_message(chat_id, "Providers:\n" + "\n".join(self.bridge.available_providers().keys()))
        elif cmd == "/improve":
            self._send_message(chat_id, "Skills improvement not yet implemented for this deployment.")
        elif cmd == "/secrets":
            s = self.bridge.status() if self.bridge else {}
            self._send_message(chat_id, "Provider: " + s.get("provider", "?") + "\nComposio: " + str(bool(getattr(self.bridge, "_composio", None))) + "\nFirecrawl: via Composio")
        elif cmd == "/restart":
            self._send_message(chat_id, "Restart Space from Hugging Face UI -> Settings -> Restart Space.")
        elif cmd in ("/reconfigure", "/reconfig"):
            self.enqueue_webhook()
            self.configure_commands()
            self._send_message(chat_id, "Webhook + commands re-enqueued for relay.")
        elif cmd == "/schedule":
            if not arg:
                self._menu_msg_id.pop(chat_id, None)
                await self._show_menu(chat_id, "schedule")
            else:
                sub_parts = arg.split(maxsplit=1)
                sub_cmd = sub_parts[0].lower()
                sub_arg = sub_parts[1].strip() if len(sub_parts) > 1 else ""
                if sub_cmd == "add":
                    await self._handle_schedule_add(chat_id, sub_arg)
                elif sub_cmd == "list":
                    await _action_schedule_list(self, chat_id)
                elif sub_cmd == "remove" and sub_arg:
                    await _action_schedule_remove_by_id(self, chat_id, sub_arg)
                elif sub_cmd == "pause" and sub_arg:
                    await _action_schedule_pause_by_id(self, chat_id, sub_arg)
                elif sub_cmd == "resume" and sub_arg:
                    await _action_schedule_resume_by_id(self, chat_id, sub_arg)
                else:
                    self._send_message(chat_id, "Usage:\n/schedule add <description>\n/schedule list\n/schedule remove <id>\n/schedule pause <id>\n/schedule resume <id>")

    def _enqueue_typing(self, chat_id: int) -> None:
        with self._outbox_lock:
            self.outbox.append({"_method": "sendChatAction", "chat_id": chat_id, "action": "typing"})

    async def _typing_refresher(self, chat_id: int) -> None:
        try:
            while True:
                await asyncio.sleep(3)
                self._enqueue_typing(chat_id)
        except asyncio.CancelledError:
            pass

    async def _handle_message(self, chat_id: int, text: str) -> None:
        key = str(chat_id)
        hist = self._chat_history.get(key, [])
        self._enqueue_typing(chat_id)
        refresh_task = asyncio.create_task(self._typing_refresher(chat_id))
        try:
            response = await asyncio.to_thread(self.bridge_chat, text, hist, key)
        finally:
            refresh_task.cancel()
            try:
                await refresh_task
            except asyncio.CancelledError:
                pass
        self._chat_history.setdefault(key, [])
        self._chat_history[key].extend([{"role": "user", "content": text}, {"role": "assistant", "content": response}])
        self._chat_history[key] = self._chat_history[key][-self._history_max:]
        self._send_message(chat_id, response)

    async def _handle_schedule_add(self, chat_id: int, text: str) -> None:
        """Parse /schedule add <text>, show confirmation with Yes/No inline."""
        text = text.strip()
        if not text:
            self._send_message(chat_id, "Describe your task, e.g. /schedule add check gmail every 15 minutes")
            return
        # Sweep expired pending confirmations
        now = time.time()
        self._pending_schedule = {k: v for k, v in self._pending_schedule.items() if v.get("expires_at", 0) > now}
        # Structured: text starts with a number
        interval = None
        prompt = text
        parts = text.split(maxsplit=1)
        if parts and parts[0].isdigit():
            interval = float(parts[0])
            prompt = parts[1].strip() if len(parts) > 1 else ""
        if interval is None and self.bridge:
            # NL parsing via LLM
            parsed = self.bridge.parse_schedule(text)
            if "error" in parsed:
                self._send_message(
                    chat_id,
                    "Couldn't parse a schedule from that. Try:\n"
                    "/schedule add N <description>\n"
                    "Example: /schedule add 15 check my gmail",
                )
                return
            interval = parsed.get("interval_minutes")
            prompt = parsed.get("prompt", text)
        if not interval or interval < 1 or not prompt:
            self._send_message(chat_id, "Invalid schedule. Try: /schedule add 15 check my gmail")
            return
        # Store pending
        import uuid as _uuid
        token = _uuid.uuid4().hex[:8]
        self._pending_schedule[token] = {
            "chat_id": chat_id,
            "prompt": prompt,
            "interval_minutes": interval,
            "expires_at": time.time() + 300,
        }
        # Show confirmation
        kb = {
            "inline_keyboard": [
                [
                    {"text": "✅ Confirm", "callback_data": "ac:schedule_cfm:" + token},
                    {"text": "❌ Cancel", "callback_data": "ac:schedule_del:" + token},
                ]
            ]
        }
        interval_str = f"{interval:.0f} min" if interval >= 1 else f"{interval*60:.0f} sec"
        self._send_message(
            chat_id,
            f"Confirm: run '{prompt}' every {interval_str}",
            reply_markup=kb,
        )

    # -- Inline Menu System -------------------------------------------------

    def _edit_message(self, chat_id: int, message_id: int, text: str, reply_markup: dict = None) -> None:
        """Enqueue an editMessageText to the outbox for relay delivery."""
        entry = {"_method": "editMessageText", "chat_id": chat_id, "message_id": message_id, "text": text[:4096]}
        if reply_markup:
            entry["reply_markup"] = reply_markup
        with self._outbox_lock:
            self.outbox.append(entry)

    async def _show_menu(self, chat_id: int, menu_name: str) -> None:
        """Send or edit a menu message. Edits existing menu if one was sent before."""
        menu = MENUS.get(menu_name)
        if not menu:
            return
        kb = {"inline_keyboard": menu["buttons"]}
        msg_id = self._menu_msg_id.get(chat_id)
        if msg_id:
            self._edit_message(chat_id, msg_id, menu["text"], reply_markup=kb)
        else:
            self._send_message(chat_id, menu["text"], reply_markup=kb)

    async def _handle_callback(self, cb: dict) -> None:
        """Route callback_query: navigation (mn:*) or action (ac:*)."""
        chat_id = cb.get("message", {}).get("chat", {}).get("id")
        data = cb.get("data", "")
        cb_id = cb.get("id")
        msg_id = cb.get("message", {}).get("message_id")
        if not chat_id or not cb_id:
            return
        # Acknowledge the callback so Telegram stops the loading spinner
        self._send_callback_answer(cb_id, "")
        if msg_id:
            self._menu_msg_id[chat_id] = msg_id
        if data.startswith("mn:"):
            await self._show_menu(chat_id, data[3:])
        elif data.startswith("ac:model:"):
            model = data[9:]
            if model:
                await _action_model_switch(self, chat_id, model)
        elif data.startswith("ac:schedule_cfm:"):
            token = data[16:]
            pending = self._pending_schedule.pop(token, None)
            if not pending or pending.get("chat_id") != chat_id:
                self._send_message(chat_id, "Confirmation expired or invalid. Try /schedule add again.")
                return
            if pending.get("expires_at", 0) < time.time():
                self._send_message(chat_id, "Confirmation expired. Try /schedule add again.")
                return
            if not self.scheduler:
                self._send_message(chat_id, "Scheduler not available.")
                return
            r = self.scheduler.add_job(chat_id, pending["prompt"], pending["interval_minutes"])
            if "error" in r:
                self._send_message(chat_id, "Failed: " + r["error"])
            else:
                next_s = time.strftime("%H:%M", time.localtime(r["next_run_at"]))
                self._send_message(chat_id, f"✅ Job created! ID: {r['id']}\nNext run at {next_s}, then every {pending['interval_minutes']:.0f} min.")
        elif data.startswith("ac:schedule_del:"):
            token = data[16:]
            self._pending_schedule.pop(token, None)
            self._send_callback_answer(cb_id, "Cancelled")
        elif data.startswith("ac:schedule_rmv:"):
            job_id = data[16:]
            await _action_schedule_remove_by_id(self, chat_id, job_id)
        elif data.startswith("ac:schedule_ps:"):
            job_id = data[15:]
            await _action_schedule_pause_by_id(self, chat_id, job_id)
        elif data.startswith("ac:schedule_rs:"):
            job_id = data[15:]
            await _action_schedule_resume_by_id(self, chat_id, job_id)
        elif data.startswith("ac:"):
            handler = MENU_ACTIONS_ASYNC.get(data[3:])
            if handler:
                try:
                    await handler(self, chat_id)
                except Exception as e:
                    logger.exception("Action handler failed for %s", data[3:])
                    self._send_message(chat_id, "Error: " + str(e)[:200])
            else:
                self._send_message(chat_id, "Unknown action: " + data[3:])

    def _send_message(self, chat_id: int, text: str, **extra) -> None:
        with self._outbox_lock:
            self.outbox.append({"_method": "sendMessage", "chat_id": chat_id, "text": (text or "")[:4096], **extra})

    def _send_callback_answer(self, callback_query_id: str, text: str = "") -> None:
        with self._outbox_lock:
            self.outbox.append({"_method": "answerCallbackQuery", "callback_query_id": callback_query_id, "text": text})

    # -- Direct-send emergency fallback (manual only, not auto-started) ----

    _TELEGRAM_PATHS = {
        "sendMessage": "/sendMessage",
        "editMessageText": "/editMessageText",
        "answerCallbackQuery": "/answerCallbackQuery",
        "setWebhook": "/setWebhook",
        "setMyCommands": "/setMyCommands",
        "setChatMenuButton": "/setChatMenuButton",
    }

    def _send_direct(self, msg: dict) -> bool:
        """Try calling api.telegram.org directly. Returns True if sent."""
        msg = dict(msg)
        method = msg.pop("_method", "sendMessage")
        path = self._TELEGRAM_PATHS.get(method, "/sendMessage")
        try:
            req = urllib.request.Request(
                "https://api.telegram.org/bot" + self.token + path,
                data=json.dumps(msg).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode()).get("ok", False)
        except Exception:
            return False

    async def drain_outbox(self) -> list[dict]:
        with self._outbox_lock:
            out = list(self.outbox)
            self.outbox.clear()
        if out:
            self._sent_count += len(out)
            logger.info("Outbox drained %d items: %s", len(out), [m.get("_method") for m in out[:5]])
        return out

    async def peek_outbox(self) -> list[dict]:
        """Return outbox items without draining (for diagnostics)."""
        with self._outbox_lock:
            return list(self.outbox)

    def drain_voice_queue(self) -> list[dict]:
        with self._voice_lock:
            out = list(self._voice_queue)
            self._voice_queue.clear()
            return out

    # -- Inbound getUpdates polling (bypass webhook cold-boot issue) --------

    async def _polling_worker(self) -> None:
        """Long-poll Telegram getUpdates, enqueue into processing queue."""
        while self._initialized and self._use_polling:
            try:
                params = {"offset": self._poll_offset, "timeout": 30, "allowed_updates": ["message", "edited_message", "callback_query"]}
                req = urllib.request.Request(
                    f"https://api.telegram.org/bot{self.token}/getUpdates",
                    data=json.dumps(params).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                resp = await asyncio.to_thread(urllib.request.urlopen, req, timeout=35)
                data = json.loads(resp.read().decode())
                results = data.get("result", [])
                if results:
                    self._poll_offset = results[-1]["update_id"] + 1
                    for update in results:
                        self.enqueue_update(update)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(5)  # transient error, retry without thrash

    async def stop(self) -> None:
        self._initialized = False

    def status(self) -> dict:
        with self._queue_lock:
            q = len(self._queue)
        with self._outbox_lock:
            o = len(self.outbox)
        with self._voice_lock:
            v = len(self._voice_queue)
        return {"configured": self.configured, "initialized": self._initialized, "uptime_seconds": round(time.time() - self._start_time, 2) if self._start_time else 0, "queue_size": q, "outbox_size": o, "voice_queue": v, "queue_processed": self._queue_processed, "queue_error": self._queue_error, "active_chats": len(self._chat_history), "sent_count": self._sent_count, "sent_error": self._sent_error}


# -- Inline Menu Definition ------------------------------------------------

MENUS = {
    "main": {
        "text": "Hermes Agent - Main Menu\n\nChoose a category:",
        "buttons": [
            [{"text": "🌐 Web", "callback_data": "mn:web"}],
            [{"text": "🧠 Memory", "callback_data": "mn:memory"}],
            [{"text": "💬 Chat", "callback_data": "mn:chat"}],
            [{"text": "🎤 Voice & Minutes", "callback_data": "mn:voice"}],
            [{"text": "⚙️ System", "callback_data": "mn:system"}],
            [{"text": "⏰ Schedule", "callback_data": "mn:schedule"}],
        ],
    },
    "web": {
        "text": "Web Tools\n\nScrape, crawl, and search via Firecrawl (Composio).",
        "buttons": [
            [{"text": "💡 Status", "callback_data": "ac:web_status"}],
            [{"text": "🔙 Back", "callback_data": "mn:main"}],
        ],
    },
    "memory": {
        "text": "Memory\n\nFacts are auto-extracted from conversations.",
        "buttons": [
            [{"text": "📋 View Facts", "callback_data": "ac:memory_view"}],
            [{"text": "📊 Status", "callback_data": "ac:memory_status"}],
            [{"text": "🗑️ Clear Memory", "callback_data": "ac:memory_clear"}],
            [{"text": "🧹 Cleanup Low Trust", "callback_data": "ac:memory_cleanup"}],
            [{"text": "🔙 Back", "callback_data": "mn:main"}],
        ],
    },
    "chat": {
        "text": "Chat\n\nManage conversation context.",
        "buttons": [
            [{"text": "📝 Summarize", "callback_data": "ac:chat_summarize"}],
            [{"text": "🔙 Back", "callback_data": "mn:main"}],
        ],
    },
    "voice": {
        "text": "Voice & Minutes\n\nSend a voice memo for transcription and minutes.",
        "buttons": [
            [{"text": "📊 Queue Status", "callback_data": "ac:voice_queue"}],
            [{"text": "🔙 Back", "callback_data": "mn:main"}],
        ],
    },
    "system": {
        "text": "System\n\nBot status, provider info, diagnostics.",
        "buttons": [
            [{"text": "ℹ️ Status", "callback_data": "ac:system_status"}],
            [{"text": "🔌 Provider Info", "callback_data": "ac:system_provider"}],
            [{"text": "🤖 Switch Model", "callback_data": "mn:model"}],
            [{"text": "⏱️ Uptime", "callback_data": "ac:system_uptime"}],
            [{"text": "📈 Queue Stats", "callback_data": "ac:system_queue"}],
            [{"text": "🌐 Composio", "callback_data": "ac:system_composio"}],
            [{"text": "🔙 Back", "callback_data": "mn:main"}],
        ],
    },
    "model": {
        "text": "Switch Model (router_0)\n\nPick a model below. The new model loads immediately.",
        "buttons": [
            [{"text": "⚡ oc/deepseek-v4-flash-free", "callback_data": "ac:model:oc/deepseek-v4-flash-free"}],
            [{"text": "🌱 mmf/mimo-auto", "callback_data": "ac:model:mmf/mimo-auto"}],
            [{"text": "🔙 Back", "callback_data": "mn:system"}],
        ],
    },
    "schedule": {
        "text": "Scheduled Tasks\n\nPeriodic jobs run automatically.\n\nTo add: /schedule add <description>\nExample: /schedule add check my gmail every 15 minutes",
        "buttons": [
            [{"text": "➕ Add Task", "callback_data": "ac:schedule_add"}],
            [{"text": "📋 List Tasks", "callback_data": "ac:schedule_list"}],
            [{"text": "🔙 Back", "callback_data": "mn:main"}],
        ],
    },
}


# -- Action Handlers -------------------------------------------------------

async def _action_web_status(bot: TelegramBot, chat_id: int) -> None:
    composio = getattr(bot.bridge, "_composio", None) if bot.bridge else None
    if not composio:
        bot._send_message(chat_id, "Web tools (Firecrawl) not available — Composio not configured.")
        return
    s = composio.status()
    bot._send_message(chat_id, "Web Tools (Firecrawl via Composio)\n\nReady: " + str(s.get("ready", False)) + "\nTools: " + str(s.get("tool_count", 0)) + "\nError: " + str(s.get("error", "none")))


async def _action_memory_view(bot: TelegramBot, chat_id: int) -> None:
    ms = bot.bridge.memory_store if bot.bridge else None
    if not ms:
        bot._send_message(chat_id, "Memory system not available.")
        return
    s = ms.status()
    count = s.get("fact_count", 0)
    if count == 0:
        bot._send_message(chat_id, "Memory\n\nNo facts stored yet. Facts are auto-extracted during conversations.")
        return
    top = s.get("top_facts", [])
    lines = []
    for f in top[:5]:
        ts = f.get("created_at", 0)
        rel = str(int(time.time() - ts)) + "s ago" if ts else ""
        trust = f.get("trust_score", 0.5)
        bar = "🟢" if trust >= 0.7 else ("🟡" if trust >= 0.4 else "🔴")
        lines.append(bar + " " + f["content"][:150] + " (" + rel + ")")
    bot._send_message(chat_id, "Memory (" + str(count) + " facts)\n\n" + "\n".join(lines))


async def _action_memory_status(bot: TelegramBot, chat_id: int) -> None:
    ms = bot.bridge.memory_store if bot.bridge else None
    if not ms:
        bot._send_message(chat_id, "Memory not available.")
        return
    s = ms.status()
    bot._send_message(chat_id, "Memory Status\n\nFacts: " + str(s["fact_count"]) + "\nAvg trust: " + str(round(s.get("avg_trust", 0), 2)) + "\nAuto-extract: " + str(bot.bridge.memory_enabled if bot.bridge else "?"))


async def _action_memory_clear(bot: TelegramBot, chat_id: int) -> None:
    ms = bot.bridge.memory_store if bot.bridge else None
    if not ms:
        bot._send_message(chat_id, "Memory not available.")
        return
    ms.clear(scope=str(chat_id))
    bot._send_message(chat_id, "Memory cleared for this chat.")


async def _action_memory_cleanup(bot: TelegramBot, chat_id: int) -> None:
    ms = bot.bridge.memory_store if bot.bridge else None
    if not ms:
        bot._send_message(chat_id, "Memory not available.")
        return
    n = ms.cleanup_low_trust()
    bot._send_message(chat_id, "Cleanup complete. Removed " + str(n) + " low-trust facts.")


async def _action_chat_summarize(bot: TelegramBot, chat_id: int) -> None:
    if not bot.bridge:
        bot._send_message(chat_id, "Bridge not available.")
        return
    try:
        response = await asyncio.to_thread(bot.bridge_chat, "Summarize the conversation so far in 3-4 bullet points.", [], str(chat_id))
        bot._send_message(chat_id, "Summary\n\n" + response)
    except Exception as e:
        bot._send_message(chat_id, "Summary failed: " + str(e)[:200])


async def _action_voice_queue(bot: TelegramBot, chat_id: int) -> None:
    bot._send_message(chat_id, "Voice Queue\n\nPending: " + str(len(bot._voice_queue)))


async def _action_system_status(bot: TelegramBot, chat_id: int) -> None:
    tg = bot.status()
    lines = ["System Status"]
    if bot.bridge:
        b = bot.bridge.status()
        lines.append("Provider: " + str(b.get("provider", "?")))
        lines.append("Model: " + str(b.get("model", "?")))
        lines.append("Ready: " + str(b.get("ready", False)))
    lines.append("Uptime: " + str(tg["uptime_seconds"]) + "s")
    lines.append("Queue: " + str(tg["queue_size"]) + " / " + str(tg["queue_processed"]) + " processed")
    bot._send_message(chat_id, "\n".join(lines))


async def _action_system_provider(bot: TelegramBot, chat_id: int) -> None:
    if not bot.bridge:
        bot._send_message(chat_id, "Bridge not available.")
        return
    b = bot.bridge.status()
    bot._send_message(chat_id, "Provider Info\n\nProvider: " + str(b.get("provider", "?")) + "\nModel: " + str(b.get("model", "?")) + "\nReady: " + str(b.get("ready", False)) + "\nError: " + str(b.get("error", "none")))


async def _action_system_uptime(bot: TelegramBot, chat_id: int) -> None:
    tg = bot.status()
    uptime = int(tg["uptime_seconds"])
    days, rem = divmod(uptime, 86400)
    hours, rem = divmod(rem, 3600)
    mins, secs = divmod(rem, 60)
    bot._send_message(chat_id, "Uptime\n\n" + str(days) + "d " + str(hours) + "h " + str(mins) + "m " + str(secs) + "s")


async def _action_system_queue(bot: TelegramBot, chat_id: int) -> None:
    tg = bot.status()
    bot._send_message(chat_id, "Queue Stats\n\nPending: " + str(tg["queue_size"]) + "\nProcessed: " + str(tg["queue_processed"]) + "\nError: " + (str(tg["queue_error"]) if tg["queue_error"] else "none"))


async def _action_model_switch(bot: TelegramBot, chat_id: int, model: str) -> None:
    if not bot.bridge:
        bot._send_message(chat_id, "Bridge not available.")
        return
    r = bot.bridge.switch_model(model)
    if r.get("success"):
        bot._send_message(chat_id, "Model switched to: " + model)
    else:
        bot._send_message(chat_id, "Failed: " + r.get("error", "unknown"))


async def _action_system_composio(bot: TelegramBot, chat_id: int) -> None:
    composio = getattr(bot.bridge, "_composio", None) if bot.bridge else None
    if not composio:
        bot._send_message(chat_id, "Composio not available.")
        return
    s = composio.status()
    bot._send_message(chat_id, "Composio\n\nReady: " + str(s.get("ready", False)) + "\nTools: " + str(s.get("tool_count", 0)) + "\nError: " + str(s.get("error", "none")))


# -- Schedule action handlers ------------------------------------------------

async def _action_schedule_add(bot: TelegramBot, chat_id: int) -> None:
    bot._send_message(chat_id, "Describe your recurring task.\n\nExample: /schedule add check gmail every 15 minutes\n\nYou can also use: /schedule add N <description>\n(where N = interval in minutes)")


async def _action_schedule_list(bot: TelegramBot, chat_id: int) -> None:
    if not bot.scheduler:
        bot._send_message(chat_id, "Scheduler not available.")
        return
    jobs = bot.scheduler.list_jobs(chat_id)
    if not jobs:
        bot._send_message(chat_id, "No scheduled tasks. Add one with /schedule add")
        return
    lines = []
    kb_rows = []
    active_count = sum(1 for j in jobs if j["status"] == "active")
    lines.append(f"Scheduled Tasks ({active_count} active, {len(jobs)} total)\n")
    for j in jobs:
        sid = j["id"]
        interval_str = f"{j['interval_minutes']:.0f}m"
        next_s = time.strftime("%H:%M", time.localtime(j["next_run_at"])) if j.get("next_run_at") else "—"
        last_s = time.strftime("%H:%M", time.localtime(j["last_run_at"])) if j.get("last_run_at") else "—"
        err = j.get("error_count", 0)
        status_icon = "⏸️" if j["status"] == "paused" else ("⏱️" if j["status"] == "active" else "❌")
        status_tag = " [PAUSED]" if j["status"] == "paused" else (" [ERRORED]" if j["status"] == "errored" else "")
        lines.append(f"{status_icon} {sid[:8]}: {j['prompt'][:50]} every {interval_str}{status_tag}")
        lines.append(f"   Next: {next_s} | Last: {last_s} | Errors: {err}")
        # Inline buttons for this job (full 12-char ID in callback_data, well under 64-byte limit)
        sid_full = sid
        rm_btn = {"text": "❌", "callback_data": f"ac:schedule_rmv:{sid_full}"}
        if j["status"] == "active":
            toggle_btn = {"text": "⏸️", "callback_data": f"ac:schedule_ps:{sid_full}"}
        elif j["status"] == "paused":
            toggle_btn = {"text": "▶️", "callback_data": f"ac:schedule_rs:{sid_full}"}
        else:
            toggle_btn = {"text": "▶️", "callback_data": f"ac:schedule_rs:{sid_full}"}
        kb_rows.append([rm_btn, toggle_btn])
    text = "\n".join(lines)
    kb = {"inline_keyboard": kb_rows} if kb_rows else None
    bot._send_message(chat_id, text, reply_markup=kb)


async def _action_schedule_remove_by_id(bot: TelegramBot, chat_id: int, job_id: str) -> None:
    if not bot.scheduler:
        bot._send_message(chat_id, "Scheduler not available.")
        return
    r = bot.scheduler.remove_job(job_id)
    if "error" in r:
        bot._send_message(chat_id, "Failed: " + r["error"])
    else:
        bot._send_message(chat_id, "✅ Job removed.")


async def _action_schedule_pause_by_id(bot: TelegramBot, chat_id: int, job_id: str) -> None:
    if not bot.scheduler:
        bot._send_message(chat_id, "Scheduler not available.")
        return
    r = bot.scheduler.pause_job(job_id)
    if "error" in r:
        bot._send_message(chat_id, "Failed: " + r["error"])
    else:
        bot._send_message(chat_id, "⏸️ Job paused.")


async def _action_schedule_resume_by_id(bot: TelegramBot, chat_id: int, job_id: str) -> None:
    if not bot.scheduler:
        bot._send_message(chat_id, "Scheduler not available.")
        return
    r = bot.scheduler.resume_job(job_id)
    if "error" in r:
        bot._send_message(chat_id, "Failed: " + r["error"])
    else:
        next_s = time.strftime("%H:%M", time.localtime(r["next_run_at"]))
        bot._send_message(chat_id, f"▶️ Job resumed. Next run at {next_s}.")


MENU_ACTIONS_ASYNC: dict[str, Callable] = {
    "web_status": _action_web_status,
    "memory_view": _action_memory_view,
    "memory_status": _action_memory_status,
    "memory_clear": _action_memory_clear,
    "memory_cleanup": _action_memory_cleanup,
    "chat_summarize": _action_chat_summarize,
    "voice_queue": _action_voice_queue,
    "system_status": _action_system_status,
    "system_provider": _action_system_provider,
    "system_uptime": _action_system_uptime,
    "system_queue": _action_system_queue,
    "system_composio": _action_system_composio,
    "schedule_add": _action_schedule_add,
    "schedule_list": _action_schedule_list,
}
