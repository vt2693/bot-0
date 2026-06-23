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
            {"command": "menu", "description": "Menu"},
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
            self._send_message(chat_id, "Voice memo received — transcribing...")
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
            self._send_message(chat_id, "Hello — Hermes Agent online. Send text or voice. Use /menu or /model.")
        elif cmd == "/menu":
            self._send_message(chat_id, "Hermes menu:\n/model — providers\n/secrets — configured systems\n/restart — Space restart info\nSend a voice memo for minutes.")
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
            self._send_message(chat_id, f"Provider: {s.get('provider')}\nComposio: {bool(getattr(self.bridge, '_composio', None))}\nBrowser: {s.get('browser')}")
        elif cmd == "/restart":
            self._send_message(chat_id, "Restart Space from Hugging Face UI → Settings → Restart Space.")

    async def _handle_message(self, chat_id: int, text: str) -> None:
        key = str(chat_id)
        hist = self._chat_history.get(key, [])
        response = await asyncio.to_thread(self.bridge_chat, text, hist, key)
        self._chat_history.setdefault(key, [])
        self._chat_history[key].extend([{"role": "user", "content": text}, {"role": "assistant", "content": response}])
        self._chat_history[key] = self._chat_history[key][-self._history_max:]
        self._send_message(chat_id, response)

    async def _handle_callback(self, cb: dict) -> None:
        chat_id = cb.get("message", {}).get("chat", {}).get("id")
        cb_id = cb.get("id")
        data = cb.get("data", "")
        if cb_id:
            self._send_callback_answer(cb_id, "")
        if chat_id:
            self._send_message(chat_id, f"Callback: {data}")

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
