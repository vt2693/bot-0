import os
import time
import json
import asyncio
import logging
import threading
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
        self._history_max = 20
        self._voice_queue: list[dict] = []
        self._voice_lock = threading.Lock()
        self._menu_msg_id: dict[int, int] = {}  # chat_id -> last menu message_id

    @property
    def configured(self) -> bool:
        return bool(self.token)

    async def initialize_async(self) -> bool:
        if not self.token:
            return False
        self._initialized = True
        self._start_time = time.time()
        self.configure_commands()
        self.enqueue_config("setWebhook", {"url": os.getenv("TELEGRAM_WEBHOOK_URL", os.getenv("SPACE_URL", "https://vt2693-bot-0.hf.space") + "/webhook/telegram"), "allowed_updates": ["message", "edited_message", "callback_query"]})
        return True

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
        ]
        self.enqueue_config("setMyCommands", {"commands": cmds})
        self.enqueue_config("setChatMenuButton", {"menu_button": {"type": "commands"}})

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
            self._send_message(chat_id, "Provider: " + s.get("provider", "?") + "\nComposio: " + str(bool(getattr(self.bridge, "_composio", None))) + "\nBrowser: " + str(s.get("browser")))
        elif cmd == "/restart":
            self._send_message(chat_id, "Restart Space from Hugging Face UI -> Settings -> Restart Space.")

    async def _handle_message(self, chat_id: int, text: str) -> None:
        key = str(chat_id)
        hist = self._chat_history.get(key, [])
        response = await asyncio.to_thread(self.bridge_chat, text, hist, key)
        self._chat_history.setdefault(key, [])
        self._chat_history[key].extend([{"role": "user", "content": text}, {"role": "assistant", "content": response}])
        self._chat_history[key] = self._chat_history[key][-self._history_max:]
        self._send_message(chat_id, response)

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

    async def drain_outbox(self) -> list[dict]:
        with self._outbox_lock:
            out = list(self.outbox)
            self.outbox.clear()
            return out

    def drain_voice_queue(self) -> list[dict]:
        with self._voice_lock:
            out = list(self._voice_queue)
            self._voice_queue.clear()
            return out

    async def stop(self) -> None:
        self._initialized = False

    def status(self) -> dict:
        with self._queue_lock:
            q = len(self._queue)
        with self._outbox_lock:
            o = len(self.outbox)
        with self._voice_lock:
            v = len(self._voice_queue)
        return {"configured": self.configured, "initialized": self._initialized, "uptime_seconds": round(time.time() - self._start_time, 2) if self._start_time else 0, "queue_size": q, "outbox_size": o, "voice_queue": v, "queue_processed": self._queue_processed, "queue_error": self._queue_error, "active_chats": len(self._chat_history)}


# -- Inline Menu Definition ------------------------------------------------

MENUS = {
    "main": {
        "text": "Hermes Agent - Main Menu\n\nChoose a category:",
        "buttons": [
            [{"text": "Web", "callback_data": "mn:web"}],
            [{"text": "Memory", "callback_data": "mn:memory"}],
            [{"text": "Chat", "callback_data": "mn:chat"}],
            [{"text": "Voice & Minutes", "callback_data": "mn:voice"}],
            [{"text": "System", "callback_data": "mn:system"}],
        ],
    },
    "web": {
        "text": "Web Tools\n\nBrowse URLs or check browser status.",
        "buttons": [
            [{"text": "Browser Status", "callback_data": "ac:web_status"}],
            [{"text": "Back", "callback_data": "mn:main"}],
        ],
    },
    "memory": {
        "text": "Memory\n\nFacts are auto-extracted from conversations.",
        "buttons": [
            [{"text": "View Facts", "callback_data": "ac:memory_view"}],
            [{"text": "Memory Status", "callback_data": "ac:memory_status"}],
            [{"text": "Clear Memory", "callback_data": "ac:memory_clear"}],
            [{"text": "Cleanup Low Trust", "callback_data": "ac:memory_cleanup"}],
            [{"text": "Back", "callback_data": "mn:main"}],
        ],
    },
    "chat": {
        "text": "Chat\n\nManage conversation context.",
        "buttons": [
            [{"text": "Summarize", "callback_data": "ac:chat_summarize"}],
            [{"text": "Back", "callback_data": "mn:main"}],
        ],
    },
    "voice": {
        "text": "Voice & Minutes\n\nSend a voice memo for transcription and minutes.",
        "buttons": [
            [{"text": "Queue Status", "callback_data": "ac:voice_queue"}],
            [{"text": "Back", "callback_data": "mn:main"}],
        ],
    },
    "system": {
        "text": "System\n\nBot status, provider info, diagnostics.",
        "buttons": [
            [{"text": "Status", "callback_data": "ac:system_status"}],
            [{"text": "Provider Info", "callback_data": "ac:system_provider"}],
            [{"text": "Uptime", "callback_data": "ac:system_uptime"}],
            [{"text": "Queue Stats", "callback_data": "ac:system_queue"}],
            [{"text": "Composio", "callback_data": "ac:system_composio"}],
            [{"text": "Back", "callback_data": "mn:main"}],
        ],
    },
}


# -- Action Handlers -------------------------------------------------------

async def _action_web_status(bot: TelegramBot, chat_id: int) -> None:
    browser = getattr(bot.bridge, "_browser", None) if bot.bridge else None
    if not browser:
        bot._send_message(chat_id, "Browser not available (no cpu-upgrade tier).")
        return
    s = browser.status()
    bot._send_message(chat_id, "Browser Status\n\nReady: " + str(s.get("ready", False)) + "\nError: " + str(s.get("error", "none")))


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
        bar = "[G]" if trust >= 0.7 else ("[Y]" if trust >= 0.4 else "[R]")
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


async def _action_system_composio(bot: TelegramBot, chat_id: int) -> None:
    composio = getattr(bot.bridge, "_composio", None) if bot.bridge else None
    if not composio:
        bot._send_message(chat_id, "Composio not available.")
        return
    s = composio.status()
    bot._send_message(chat_id, "Composio\n\nReady: " + str(s.get("ready", False)) + "\nTools: " + str(s.get("tool_count", 0)) + "\nError: " + str(s.get("error", "none")))


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
}
