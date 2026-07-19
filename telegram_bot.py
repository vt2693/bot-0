import os
import time
import json  # noqa: F811
import asyncio
import logging
import re
import threading
import urllib.request
import urllib.error
from typing import Callable
import httpx

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
        self._pending_skills: dict[str, dict] = {}
        self._tts_chats: set[int] = set()    # chat_ids with TTS enabled
        self._tts_models: dict[int, str] = {}  # chat_id -> model name override
        self._subtask_parents: dict[int, str] = {}  # chat_id -> parent issue key for back button
        epics_raw = os.getenv("JIRA_EPICS", "")
        self.jira_epics = [e.strip() for e in epics_raw.split(",") if e.strip()]

    @property
    def configured(self) -> bool:
        return bool(self.token)

    async def initialize_async(self) -> bool:
        if not self.token:
            return False
        self._initialized = True
        self._start_time = time.time()
        self.configure_commands()
        # Webhook registration + outbound delivery go through the relay
        # (server on free tier blocks api.telegram.org — SSL handshake times out).
        # The relay polls /api/tg_outbox for outbound, and runs getUpdates
        # polling for inbound delivery to /webhook/telegram.
        self.enqueue_webhook()
        # Restore TTS state from memory_store (all scopes)
        if self.bridge and self.bridge.memory_store:
            try:
                results = self.bridge.memory_store.search("tts_enabled", "", 500)
                tts_by_scope: dict[str, int] = {}
                for r in results:
                    content = r["content"].strip().lower()
                    if content in ("tts_enabled=true", "tts_enabled=false"):
                        scope = r.get("scope", "")
                        rid = r.get("id", 0)
                        # latest fact per scope wins
                        if scope not in tts_by_scope or rid > tts_by_scope[scope]:
                            tts_by_scope[scope] = rid
                for r in results:
                    scope = r.get("scope", "")
                    rid = r.get("id", 0)
                    if tts_by_scope.get(scope) == rid and r["content"].strip().lower() == "tts_enabled=true":
                        try:
                            self._tts_chats.add(int(scope))
                        except (ValueError, TypeError):
                            pass
            except Exception:
                pass
        # Restore TTS model from memory_store
        if self.bridge and self.bridge.memory_store:
            try:
                results = self.bridge.memory_store.search("tts_model", "", 500)
                latest_by_scope: dict[str, dict] = {}
                for r in results:
                    scope = r.get("scope", "")
                    rid = r.get("id", 0)
                    if scope not in latest_by_scope or rid > latest_by_scope[scope]["id"]:
                        latest_by_scope[scope] = r
                for scope, r in latest_by_scope.items():
                    content = r["content"].strip()
                    if content.startswith("tts_model="):
                        model = content[10:]
                        if model:
                            try:
                                self._tts_models[int(scope)] = model
                            except (ValueError, TypeError):
                                pass
            except Exception:
                pass
        return True

    def enqueue_webhook(self) -> None:
        """Re-enqueue webhook config (callable from /reconfigure)."""
        self.enqueue_config("setWebhook", {"url": os.getenv("TELEGRAM_WEBHOOK_URL", "") + "/webhook/telegram", "allowed_updates": ["message", "edited_message", "callback_query"]})

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
            self._send_message(chat_id, "/start /menu /model /secrets. Ask normally to chat.")
        elif cmd == "/model":
            if not self.bridge:
                self._send_message(chat_id, "Bridge unavailable")
                return
            if arg:
                self._send_message(chat_id, str(self.bridge.switch_provider(arg)))
            else:
                self._send_message(chat_id, "Providers:\n" + "\n".join(self.bridge.available_providers().keys()))
        elif cmd == "/improve":
            await self._handle_improve(chat_id, arg)
        elif cmd == "/secrets":
            s = self.bridge.status() if self.bridge else {}
            self._send_message(chat_id, "Provider: " + s.get("provider", "?") + "\nComposio: " + str(bool(getattr(self.bridge, "_composio", None))) + "\nFirecrawl: via Composio")
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
        # Check for skill-edit continuation before sending text to LLM
        edit_key = None
        for k, v in list(self._pending_skills.items()):
            if k.endswith("_editing") and v.get("chat_id") == chat_id:
                edit_key = k
                break
        if edit_key:
            edit_info = self._pending_skills.pop(edit_key, None)
            if edit_info:
                skill_id = edit_info.get("skill_id")
                if skill_id and self.bridge and self.bridge.memory_store:
                    if self.bridge.memory_store.skill_update(int(skill_id), procedure=text):
                        self._send_message(chat_id, f"✅ Skill {skill_id} procedure updated.")
                    else:
                        self._send_message(chat_id, "Edit failed: skill not found.")
                    return
                orig_token = edit_info.get("orig_token")
                pending = self._pending_skills.get(orig_token) if orig_token else None
                if pending and pending.get("chat_id") == chat_id:
                    skill = pending["skill"]
                    skill["procedure"] = text
                    self._send_message(chat_id, "✅ Procedure updated. Review and save:")
                    self._show_skill_confirmation(chat_id, skill)
                else:
                    self._send_message(chat_id, "Edit session expired.")
            return
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
        skill_info = None
        if isinstance(response, str) and response.startswith('{"_skill_detected'):
            try:
                parsed = json.loads(response)
                skill_info = parsed.get("_skill_detected")
                response = parsed.get("response", "")
            except (json.JSONDecodeError, TypeError):
                pass
        self._chat_history[key].extend([{"role": "user", "content": text}, {"role": "assistant", "content": response}])
        self._chat_history[key] = self._chat_history[key][-self._history_max:]
        self._send_message(chat_id, response)
        # Auto-TTS if enabled for this chat
        if chat_id in self._tts_chats:
            model = self._tts_models.get(chat_id, "")
            asyncio.create_task(self._send_tts_async(chat_id, response, model))
        if skill_info:
            await self._show_skill_confirmation(chat_id, skill_info)

    def _show_skill_confirmation(self, chat_id: int, skill: dict) -> None:
        """Send inline confirmation for a detected skill."""
        import uuid as _uuid
        token = _uuid.uuid4().hex[:8]
        self._pending_skills[token] = {
            "chat_id": chat_id,
            "skill": skill,
            "expires_at": time.time() + 300,
        }
        title = skill.get("title", "?")[:80]
        problem = skill.get("problem", "?")[:200]
        procedure = skill.get("procedure", "?")[:300]
        text = (
            f"📘 Potential skill learned:\n\n"
            f"Title: {title}\n"
            f"Trigger: {problem}\n"
            f"Steps: {procedure}\n"
        )
        failure = skill.get("failure_pattern", "")
        if failure:
            text += f"Avoid: {failure[:200]}\n"
        kb = {
            "inline_keyboard": [
                [
                    {"text": "💾 Save", "callback_data": f"ac:skill_save:{token}"},
                    {"text": "📝 Edit", "callback_data": f"ac:skill_edit:{token}"},
                    {"text": "❌ Discard", "callback_data": f"ac:skill_discard:{token}"},
                ]
            ]
        }
        self._send_message(chat_id, text, reply_markup=kb)

    def _pending_skill_cleanup(self) -> None:
        now = time.time()
        self._pending_skills = {k: v for k, v in self._pending_skills.items() if v.get("expires_at", 0) > now}

    async def _handle_improve(self, chat_id: int, arg: str) -> None:
        ms = self.bridge.memory_store if self.bridge else None
        if not ms:
            self._send_message(chat_id, "Memory system not available.")
            return
        parts = arg.split(maxsplit=1) if arg else []
        sub = parts[0].lower() if parts else ""
        sub_arg = parts[1].strip() if len(parts) > 1 else ""
        if not sub:
            # List all skills
            skills = ms.skill_list(str(chat_id))
            if not skills:
                self._send_message(chat_id, "No skills saved yet. Skills are auto-detected with AUTO_LEARN=true.")
                return
            lines = [f"Skills ({len(skills)} total):\n"]
            for s in skills:
                icon = "🟢" if s["status"] == "active" else ("🟡" if s["status"] == "unverified" else "⚪")
                lines.append(f"{icon} {s['id']}: {s['title'][:80]}")
            self._send_message(chat_id, "\n".join(lines))
        elif sub == "search" and sub_arg:
            results = ms.skill_search(sub_arg, str(chat_id), 10)
            if not results:
                self._send_message(chat_id, f"No skills matching: {sub_arg}")
                return
            lines = [f"Skills matching '{sub_arg}':\n"]
            for s in results:
                lines.append(f"{s['id']}: {s['title'][:80]}")
            self._send_message(chat_id, "\n".join(lines))
        elif sub in ("delete", "del", "rm") and sub_arg:
            try:
                sid = int(sub_arg)
            except ValueError:
                self._send_message(chat_id, "Usage: /improve delete <id>")
                return
            if ms.skill_remove(sid):
                self._send_message(chat_id, f"✅ Skill {sid} deleted.")
            else:
                self._send_message(chat_id, f"Skill {sid} not found.")
        elif sub == "edit" and sub_arg:
            try:
                sid = int(sub_arg)
            except ValueError:
                self._send_message(chat_id, "Usage: /improve edit <id>")
                return
            s = ms.skill_get(sid)
            if not s:
                self._send_message(chat_id, f"Skill {sid} not found.")
                return
            token = f"edit_{sid}_{int(time.time())}"
            self._pending_skills[token + "_editing"] = {
                "chat_id": chat_id,
                "skill_id": sid,
                "step": "procedure",
                "expires_at": time.time() + 300,
            }
            self._send_message(chat_id, f"Send the new procedure text for skill {sid} now.")
        elif sub == "export":
            skills = ms.skill_list(str(chat_id))
            blob = json.dumps(skills, indent=2, default=str)
            for chunk in [blob[i:i+3900] for i in range(0, len(blob), 3900)]:
                self._send_message(chat_id, chunk)
        else:
            # Try showing detail by ID
            try:
                sid = int(sub)
            except ValueError:
                self._send_message(chat_id, "Usage: /improve [list|search <q>|edit <id>|delete <id>|export]")
                return
            s = ms.skill_get(sid)
            if not s:
                self._send_message(chat_id, f"Skill {sid} not found.")
                return
            text = (
                f"Skill {s['id']} — {s['status']}\n\n"
                f"Title: {s['title']}\n"
                f"Problem: {s['problem']}\n"
                f"Procedure: {s['procedure']}\n"
            )
            if s["failure_pattern"]:
                text += f"Failure pattern: {s['failure_pattern']}\n"
            text += f"\nUsage: {s['access_count']}× | Injected: {s['injection_count']}× | Created: {time.strftime('%Y-%m-%d', time.localtime(s['created_at']))}"
            self._send_message(chat_id, text)

    async def _handle_schedule_add(self, chat_id: int, text: str) -> None:
        """Parse /schedule add <text>, show confirmation with Yes/No inline."""
        text = text.strip()
        if not text:
            self._send_message(chat_id, "Describe your task, e.g. /schedule add check gmail every 15 minutes")
            return
        # Sweep expired pending confirmations
        now = time.time()
        self._pending_schedule = {k: v for k, v in self._pending_schedule.items() if v.get("expires_at", 0) > now}
        # Structured: text starts with a number (always interval)
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
            # Check for absolute_epoch (new) vs interval (existing)
            if "absolute_epoch" in parsed:
                absolute_epoch = parsed["absolute_epoch"]
                prompt = parsed.get("prompt", text)
                import uuid as _uuid
                token = _uuid.uuid4().hex[:8]
                self._pending_schedule[token] = {
                    "chat_id": chat_id,
                    "prompt": prompt,
                    "absolute_epoch": absolute_epoch,
                    "interval_minutes": 0,
                    "mode": "once",  # default, overridden by button
                    "expires_at": time.time() + 300,
                }
                time_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(absolute_epoch))
                kb = {"inline_keyboard": [[
                    {"text": "✅ Run Once", "callback_data": f"ac:schedule_cfm:{token}:once"},
                    {"text": "🔁 Daily", "callback_data": f"ac:schedule_cfm:{token}:daily"},
                    {"text": "❌ Cancel", "callback_data": f"ac:schedule_del:{token}"},
                ]]}
                self._send_message(chat_id, f"Run '{prompt}' at {time_str}", reply_markup=kb)
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
            "mode": "interval",
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
        # Patch model menu with active/default indicators
        if menu_name == "model" and self.bridge:
            active = self.bridge._model
            default = self.bridge._resolve_model()
            provider = self.bridge._provider
            text = (
                f"Switch Model ({provider})\n\n"
                f"✅ Active: {active}\n"
                f"⭐ Default: {default}\n\n"
                f"Pick a model below."
            )
            buttons = []
            for row in menu["buttons"]:
                btn = row[0]
                data = btn["callback_data"]
                if data.startswith("ac:model:"):
                    model_name = data[9:]
                    prefix = ""
                    if model_name == active:
                        prefix += "✅ "
                    if model_name == default and model_name != active:
                        prefix += "⭐ "
                    if prefix:
                        btn = dict(btn, text=prefix + btn["text"].lstrip("✅⭐ "))
                buttons.append([btn])
            kb = {"inline_keyboard": buttons}
        elif menu_name == "tts_model":
            from tg_tts import TTS_MODEL as _default_tts_model
            active = self._tts_models.get(chat_id, "")
            text = (
                f"TTS Model\n\n"
                f"✅ Active: {active or _default_tts_model}\n"
                f"⭐ Default: {_default_tts_model}\n\n"
                f"Pick a voice model below."
            )
            buttons = []
            for row in menu["buttons"]:
                btn = row[0]
                data = btn["callback_data"]
                if data.startswith("ac:tts_model:"):
                    mdl = data[13:]
                    prefix = ""
                    if mdl == active or (not active and mdl == _default_tts_model):
                        prefix += "✅ "
                    if mdl == _default_tts_model and mdl != (active or _default_tts_model):
                        prefix += "⭐ "
                    if prefix:
                        btn = dict(btn, text=prefix + btn["text"].lstrip("✅⭐ "))
                buttons.append([btn])
            kb = {"inline_keyboard": buttons}
        else:
            kb = {"inline_keyboard": menu["buttons"]}
            text = menu["text"]
        msg_id = self._menu_msg_id.get(chat_id)
        if msg_id:
            self._edit_message(chat_id, msg_id, text, reply_markup=kb)
        else:
            self._send_message(chat_id, text, reply_markup=kb)

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
        elif data.startswith("ac:tts_model:"):
            model = data[13:]
            if model:
                await _action_tts_model_switch(self, chat_id, model)
        elif data.startswith("ac:schedule_cfm:"):
            suffix = data[16:]
            mode = None  # backward compat: no :mode suffix
            if ":" in suffix:
                token, mode = suffix.split(":", 1)
            else:
                token = suffix
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
            # Priority: callback mode > pending.mode > "interval"
            if mode is None:
                mode = pending.get("mode", "interval")
            absolute_epoch = pending.get("absolute_epoch")
            interval = pending.get("interval_minutes", 0)
            if mode == "daily":
                interval = 1440
            elif mode == "once":
                interval = 0
            r = self.scheduler.add_job(chat_id, pending["prompt"], interval, mode=mode, absolute_epoch=absolute_epoch)
            if "error" in r:
                self._send_message(chat_id, "Failed: " + r["error"])
            else:
                next_s = time.strftime("%H:%M", time.localtime(r["next_run_at"]))
                if mode == "once":
                    self._send_message(chat_id, f"✅ One-time job created! ID: {r['id']}\nRuns at {next_s}.")
                elif mode == "daily":
                    self._send_message(chat_id, f"✅ Daily job created! ID: {r['id']}\nRuns daily at {next_s}.")
                else:
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
        elif data.startswith("ac:skill_save:"):
            token = data[len("ac:skill_save:"):]
            self._pending_skill_cleanup()
            pending = self._pending_skills.pop(token, None)
            if not pending or pending.get("chat_id") != chat_id:
                self._send_message(chat_id, "Confirmation expired or invalid.")
                return
            if pending.get("expires_at", 0) < time.time():
                self._send_message(chat_id, "Confirmation expired.")
                return
            skill = pending["skill"]
            ms = self.bridge.memory_store if self.bridge else None
            if not ms:
                self._send_message(chat_id, "Memory system not available.")
                return
            r = ms.skill_add(
                title=skill.get("title", "Untitled"),
                problem=skill.get("problem", ""),
                procedure=skill.get("procedure", ""),
                failure_pattern=skill.get("failure_pattern", ""),
                tags=[],
                scope=str(chat_id),
            )
            if r.get("error"):
                self._send_message(chat_id, f"Failed to save: {r['error']}")
            else:
                self._send_message(chat_id, f"✅ Skill saved! ID: {r['id']}")
        elif data.startswith("ac:skill_edit:"):
            token = data[len("ac:skill_edit:"):]
            self._pending_skill_cleanup()
            pending = self._pending_skills.get(token)
            if not pending or pending.get("chat_id") != chat_id:
                self._send_message(chat_id, "Confirmation expired or invalid.")
                return
            skill = pending["skill"]
            self._send_message(chat_id, "Send the corrected procedure text now.")
            # Store edit context for next message
            self._pending_skills[token + "_editing"] = {"chat_id": chat_id, "skill": skill, "step": "procedure", "orig_token": token, "expires_at": time.time() + 300}
        elif data.startswith("ac:skill_discard:"):
            token = data[len("ac:skill_discard:"):]
            self._pending_skills.pop(token, None)
            self._send_callback_answer(cb_id, "Discarded")
            self._send_message(chat_id, "Skill discarded.")
        elif data.startswith("ac:skill_confirm_del:"):
            sid = data[len("ac:skill_confirm_del:"):]
            self._send_message(chat_id, f"Send /improve delete {sid} to confirm deletion.")
        elif data.startswith("ac:skill_detail:"):
            sid_str = data[len("ac:skill_detail:"):]
            try:
                sid = int(sid_str)
            except ValueError:
                self._send_message(chat_id, "Invalid skill ID.")
                return
            ms = self.bridge.memory_store if self.bridge else None
            if not ms:
                self._send_message(chat_id, "Memory not available.")
                return
            s = ms.skill_get(sid)
            if not s:
                self._send_message(chat_id, f"Skill {sid} not found.")
                return
            text = (
                f"Skill {s['id']} — {s['status']}\n\n"
                f"Title: {s['title']}\n"
                f"Problem: {s['problem']}\n"
                f"Procedure: {s['procedure']}\n"
            )
            if s["failure_pattern"]:
                text += f"Failure pattern: {s['failure_pattern']}\n"
            text += f"\nUsage: {s['access_count']}× | Injected: {s['injection_count']}×"
            self._send_message(chat_id, text)
        elif data.startswith("ac:skill_autolearn_toggle"):
            ms = self.bridge.memory_store if self.bridge else None
            if not ms:
                self._send_message(chat_id, "Memory not available.")
                return
            # Toggle via a fact entry; newest exact flag wins
            current = ms.search("auto_learn", str(chat_id), 20)
            exact = [c for c in current if c["content"].strip().lower() in ("auto_learn=true", "auto_learn=false")]
            is_on = False
            if exact:
                latest = max(exact, key=lambda c: c.get("id", 0))
                is_on = latest["content"].strip().lower() == "auto_learn=true"
            if is_on:
                ms.add("auto_learn=false", str(chat_id))
                self._send_message(chat_id, "⚙️ Auto-learn turned OFF.")
            else:
                ms.add("auto_learn=true", str(chat_id))
                self._send_message(chat_id, "⚙️ Auto-learn turned ON.")
        elif data.startswith("ac:skill_forget_inactive"):
            ms = self.bridge.memory_store if self.bridge else None
            if not ms:
                self._send_message(chat_id, "Memory not available.")
                return
            skills = ms.skill_list(str(chat_id))
            removed = 0
            for s in skills:
                if s["status"] == "inactive":
                    ms.skill_remove(s["id"])
                    removed += 1
            self._send_message(chat_id, f"Removed {removed} inactive skills.")
        elif data.startswith("ac:jira_run:"):
            await _action_jira_run(self, chat_id, data[12:])
        elif data.startswith("ac:jira_show:"):
            await _action_jira_show(self, chat_id, data[13:])
        elif data.startswith("ac:jira_task:"):
            await _action_jira_subtasks(self, chat_id, data[13:])
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
            text = (text or "")[:4096 * 10]  # hard safety cap (10 messages max)
            while text:
                chunk = text[:4096]
                text = text[4096:]
                self.outbox.append({"_method": "sendMessage", "chat_id": chat_id, "text": chunk, **extra})
                extra.pop("reply_markup", None)  # only first chunk gets keyboard

    def _send_callback_answer(self, callback_query_id: str, text: str = "") -> None:
        with self._outbox_lock:
            self.outbox.append({"_method": "answerCallbackQuery", "callback_query_id": callback_query_id, "text": text})

    # -- Direct-send emergency fallback (manual only, not auto-started) ----

    _TELEGRAM_PATHS = {
        "sendChatAction": "/sendChatAction",
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
        body = json.dumps(msg).encode()
        for attempt in range(3):
            try:
                req = urllib.request.Request(
                    "https://api.telegram.org/bot" + self.token + path,
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    return json.loads(resp.read().decode()).get("ok", False)
            except Exception:
                if attempt < 2:
                    import time as _time
                    _time.sleep(1.5 ** attempt)
                continue
        return False

    def _send_voice_direct(self, chat_id: int, audio_bytes: bytes) -> bool:
        """Send Opus audio as a voice message directly to Telegram API.

        Uses httpx multipart upload (cannot go through JSON-only relay).
        Shows record_voice action first via outbox. Retries with backoff
        on failure (same pattern as _send_direct).

        Returns True if Telegram returned {"ok": true}.
        """
        try:
            with self._outbox_lock:
                self.outbox.append({"_method": "sendChatAction", "chat_id": chat_id, "action": "record_voice"})
        except Exception:
            pass
        for attempt in range(3):
            try:
                resp = httpx.post(
                    f"https://api.telegram.org/bot{self.token}/sendVoice",
                    files={"voice": ("voice.ogg", audio_bytes, "audio/ogg")},
                    data={"chat_id": chat_id},
                    timeout=180,
                )
                data = resp.json()
                ok = data.get("ok", False)
                if ok:
                    return True
                logger.warning("sendVoice direct attempt %d returned !ok: %s", attempt + 1, data)
            except Exception as exc:
                logger.warning("sendVoice direct attempt %d failed for chat %s: %s", attempt + 1, chat_id, exc)
            time.sleep(1.5 ** attempt)
        return False


    async def _send_tts_async(self, chat_id: int, text: str, model: str = "") -> None:
        """Background task: synthesize TTS, send voice messages.

        Called via asyncio.create_task — errors are caught and logged.
        Text reply already sent by caller; this is best-effort audio.

        Long responses are split at sentence boundaries into multiple
        voice messages (~1200 chars per chunk max, ~80s audio each).
        """
        if not text or not text.strip():
            logger.warning("TTS skipped for chat %s: response text is empty", chat_id)
            return
        try:
            chunks = _split_tts_text(text.strip(), 1200)
        except Exception as exc:
            logger.warning("TTS split failed for chat %s: %s — falling back to raw text", chat_id, exc)
            chunks = [text.strip()[:4000]]
        if not chunks:
            logger.warning("TTS no chunks for chat %s", chat_id)
            return
        logger.info("TTS %s: %d chars → %d chunks", chat_id, len(text), len(chunks))
        from tg_tts import synthesize as _tts_synthesize
        from tg_tts import to_opus as _tts_to_opus
        for i, chunk in enumerate(chunks):
            t0 = time.time()
            try:
                mp3 = await asyncio.to_thread(_tts_synthesize, chunk, "", model)
                if not mp3:
                    logger.warning("TTS chunk %d/%d returned empty for chat %s", i + 1, len(chunks), chat_id)
                    continue
                opus = await asyncio.to_thread(_tts_to_opus, mp3)
                ok = self._send_voice_direct(chat_id, opus)
                logger.info("TTS chunk %d/%d chat %s: synth=%ds send=%s", i + 1, len(chunks), chat_id, time.time() - t0, ok)
                if i < len(chunks) - 1:
                    await asyncio.sleep(1.0)
            except Exception as exc:
                logger.warning("TTS chunk %d/%d failed for chat %s: %s", i + 1, len(chunks), chat_id, exc)

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

    # -- Inbound via webhook only (relay registers webhook externally) -----
    # Server on free tier cannot reach api.telegram.org (SSL handshake may time out).
    # polling -> /webhook/telegram and outbox draining -> api.telegram.org.

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
            [{"text": "📘 Skills", "callback_data": "mn:skills"}],
            [{"text": "⚙️ System", "callback_data": "mn:system"}],
            [{"text": "⏰ Schedule", "callback_data": "mn:schedule"}],
            [{"text": "📋 Jira", "callback_data": "mn:jira"}],
        ],
    },
    "jira": {
        "text": "Jira\n\nManage and browse Jira issues.",
        "buttons": [
            [{"text": "📋 Open Tasks", "callback_data": "ac:jira_open_tasks"}],
            [{"text": "🔙 Back", "callback_data": "mn:main"}],
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
        "text": "Voice & Minutes\n\nSend a voice memo for transcription and minutes.\n"
                "Toggle TTS to have text replies spoken aloud.",
        "buttons": [
            [{"text": "📊 Queue Status", "callback_data": "ac:voice_queue"}],
            [{"text": "🔊 TTS On/Off", "callback_data": "ac:tts_toggle"}],
            [{"text": "🎤 TTS Model", "callback_data": "mn:tts_model"}],
            [{"text": "🔙 Back", "callback_data": "mn:main"}],
        ],
    },
    "tts_model": {
        "text": "TTS Model\n\nPick a TTS voice model.",
        "buttons": [
            [{"text": "edge-tts/en-US-AndrewMultilingualNeural", "callback_data": "ac:tts_model:edge-tts/en-US-AndrewMultilingualNeural"}],
            [{"text": "edge-tts/en-US-EmmaMultilingualNeural", "callback_data": "ac:tts_model:edge-tts/en-US-EmmaMultilingualNeural"}],
            [{"text": "🔙 Back", "callback_data": "mn:voice"}],
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
        "text": "Switch Model",  # placeholder, overridden dynamically in _show_menu
        "buttons": [
            [{"text": "⚡ oc/deepseek-v4-flash-free", "callback_data": "ac:model:oc/deepseek-v4-flash-free"}],
            [{"text": "🌱 oc/hy3-free", "callback_data": "ac:model:oc/hy3-free"}],
            [{"text": "⬡ ollama/minimax-m3", "callback_data": "ac:model:ollama/minimax-m3"}],
            [{"text": "🆓 openrouter/nvidia/nemotron-3-ultra-550b-a55b:free", "callback_data": "ac:model:openrouter/nvidia/nemotron-3-ultra-550b-a55b:free"}],
            [{"text": "🆕 openrouter/openrouter/free", "callback_data": "ac:model:openrouter/openrouter/free"}],
            [{"text": "🤖 cx/gpt-5.4-mini", "callback_data": "ac:model:cx/gpt-5.4-mini"}],
            [{"text": "🔀 combo-high", "callback_data": "ac:model:combo-high"}],
            [{"text": "🔀 combo-medium", "callback_data": "ac:model:combo-medium"}],
            [{"text": "🔀 combo-low", "callback_data": "ac:model:combo-low"}],
            [{"text": "🔀 combo-xlow", "callback_data": "ac:model:combo-xlow"}],
            [{"text": "🔀 combo-xxlow", "callback_data": "ac:model:combo-xxlow"}],
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
    "skills": {
        "text": "📘 Skills\n\nSkills let you save reusable procedures from conversations.\n\nUse /improve for detail and management.",
        "buttons": [
            [{"text": "📋 List Skills", "callback_data": "ac:skill_list"}],
            [{"text": "🔍 Search", "callback_data": "ac:skill_search_prompt"}],
            [{"text": "⚙️ Toggle Auto-Learn", "callback_data": "ac:skill_autolearn_toggle"}],
            [{"text": "🧹 Forget Inactive", "callback_data": "ac:skill_forget_inactive"}],
            [{"text": "🔙 Back", "callback_data": "mn:main"}],
        ],
    },
}


# -- Action Handlers -------------------------------------------------------

async def _call_composio(bot: "TelegramBot", tool_name: str, args: dict) -> dict:
    """Call a Composio tool (async, awaits directly in running loop)."""
    composio = getattr(bot.bridge, "_composio", None) if bot.bridge else None
    if not composio or not composio._ready:
        return {"error": "Composio not ready — try /menu → System → Composio"}
    try:
        return await composio.call_tool(tool_name, args) or {}
    except Exception as e:
        return {"error": str(e)}


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
    ms.clear(scope=None)
    bot._send_message(chat_id, "Memory cleared (all scopes).")


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


def _split_tts_text(text: str, max_chars: int = 1200) -> list[str]:
    """Split text at sentence boundaries, each chunk ≤ max_chars.

    Uses regex to split on sentence-ending punctuation (. ! ?) followed
    by whitespace. If a single sentence exceeds max_chars, falls back
    to a word-boundary split at max_chars.

    Args:
        text: Text to split.
        max_chars: Maximum characters per chunk (~80s audio at 15ch/s).

    Returns:
        List of text chunks, each ≤ max_chars.
    """
    if len(text) <= max_chars:
        return [text]
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks: list[str] = []
    current = ""
    for sent in sentences:
        if not sent.strip():
            continue
        if len(current) + len(sent) + 1 <= max_chars:
            current = (current + " " + sent).strip()
        else:
            if current:
                chunks.append(current)
            if len(sent) > max_chars:
                words = sent.split()
                temp = ""
                for w in words:
                    if len(temp) + len(w) + 1 > max_chars:
                        if temp:
                            chunks.append(temp)
                        temp = w
                    else:
                        temp = (temp + " " + w).strip()
                current = temp
            else:
                current = sent
    if current:
        chunks.append(current)
    return chunks


async def _action_tts_toggle(bot: TelegramBot, chat_id: int) -> None:
    """Toggle TTS on/off for this chat. Persists to memory_store."""
    currently_enabled = chat_id in bot._tts_chats
    if currently_enabled:
        bot._tts_chats.discard(chat_id)
        bot._send_message(chat_id, "🔇 TTS turned OFF. Text replies will not be spoken.")
    else:
        bot._tts_chats.add(chat_id)
        bot._send_message(chat_id, "🔊 TTS turned ON. Text replies will also arrive as voice.")
    # Persist
    ms = bot.bridge.memory_store if bot.bridge else None
    if ms:
        state = "false" if currently_enabled else "true"
        ms.add(f"tts_enabled={state}", str(chat_id))


async def _action_tts_model_switch(bot: TelegramBot, chat_id: int, model: str) -> None:
    """Switch TTS model for this chat. Persists to memory_store."""
    bot._tts_models[chat_id] = model
    bot._send_message(chat_id, f"🎤 TTS model switched to {model}")
    ms = bot.bridge.memory_store if bot.bridge else None
    if ms:
        ms.add(f"tts_model={model}", str(chat_id))
    await bot._show_menu(chat_id, "tts_model")


async def _action_model_switch(bot: TelegramBot, chat_id: int, model: str) -> None:
    if not bot.bridge:
        bot._send_message(chat_id, "Bridge not available.")
        return
    r = bot.bridge.switch_model(model)
    if r.get("success"):
        await bot._show_menu(chat_id, "model")
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
    bot._send_message(chat_id, "Schedule a task.\n\n- Recurring: /schedule add check gmail every 15 minutes\n- One-shot: /schedule add check gmail at 12:00 am tomorrow\n- Structured: /schedule add 15 check gmail (interval only)")


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
        mode = j.get("mode", "interval")
        next_s = time.strftime("%H:%M", time.localtime(j["next_run_at"])) if j.get("next_run_at") else "—"
        last_s = time.strftime("%H:%M", time.localtime(j["last_run_at"])) if j.get("last_run_at") else "—"
        err = j.get("error_count", 0)
        if mode == "once":
            freq_str = "once"
        elif mode == "daily":
            freq_str = f"daily at {next_s}"
        else:
            freq_str = f"every {j['interval_minutes']:.0f}m"
        status_icon = "✅" if j["status"] == "completed" else ("⏸️" if j["status"] == "paused" else ("⏱️" if j["status"] == "active" else "❌"))
        status_tag = " [COMPLETED]" if j["status"] == "completed" else (" [PAUSED]" if j["status"] == "paused" else (" [ERRORED]" if j["status"] == "errored" else ""))
        lines.append(f"{status_icon} {sid[:8]}: {j['prompt'][:50]} ({freq_str}){status_tag}")
        lines.append(f"   Next: {next_s} | Last: {last_s} | Errors: {err}")
        # Inline buttons for this job
        sid_full = sid
        rm_btn = {"text": "❌", "callback_data": f"ac:schedule_rmv:{sid_full}"}
        if j["status"] == "completed":
            kb_rows.append([rm_btn])
        elif j["status"] == "active":
            toggle_btn = {"text": "⏸️", "callback_data": f"ac:schedule_ps:{sid_full}"}
            kb_rows.append([rm_btn, toggle_btn])
        elif j["status"] == "paused":
            toggle_btn = {"text": "▶️", "callback_data": f"ac:schedule_rs:{sid_full}"}
            kb_rows.append([rm_btn, toggle_btn])
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


# -- Skill action handlers ----------------------------------------------------


async def _action_skill_list(bot: TelegramBot, chat_id: int) -> None:
    ms = bot.bridge.memory_store if bot.bridge else None
    if not ms:
        bot._send_message(chat_id, "Memory not available.")
        return
    skills = ms.skill_list(str(chat_id))
    if not skills:
        bot._send_message(chat_id, "No skills saved yet.")
        return
    active = sum(1 for s in skills if s["status"] == "active")
    unverified = sum(1 for s in skills if s["status"] == "unverified")
    inactive = sum(1 for s in skills if s["status"] == "inactive")
    lines = [f"📘 Skills ({len(skills)} total): {active} active, {unverified} pending, {inactive} inactive\n"]
    for s in skills[:15]:
        icon = "🟢" if s["status"] == "active" else ("🟡" if s["status"] == "unverified" else "⚪")
        lines.append(f"{icon} {s['id']}: {s['title'][:80]}")
    if len(skills) > 15:
        lines.append(f"\n...and {len(skills) - 15} more. Use /improve to see all.")
    bot._send_message(chat_id, "\n".join(lines))


async def _action_skill_search_prompt(bot: TelegramBot, chat_id: int) -> None:
    bot._send_message(chat_id, "Send a search query to find matching skills.\n\nOr use: /improve search <query>")


async def _action_skill_autolearn_toggle(bot: TelegramBot, chat_id: int) -> None:
    ms = bot.bridge.memory_store if bot.bridge else None
    if not ms:
        bot._send_message(chat_id, "Memory not available.")
        return
    current = ms.search("auto_learn", str(chat_id), 20)
    exact = [c for c in current if c["content"].strip().lower() in ("auto_learn=true", "auto_learn=false")]
    is_on = False
    if exact:
        latest = max(exact, key=lambda c: c.get("id", 0))
        is_on = latest["content"].strip().lower() == "auto_learn=true"
    if is_on:
        ms.add("auto_learn=false", str(chat_id))
        bot._send_message(chat_id, "⚙️ Auto-learn turned OFF.")
    else:
        ms.add("auto_learn=true", str(chat_id))
        bot._send_message(chat_id, "⚙️ Auto-learn turned ON.")


async def _action_skill_forget_inactive(bot: TelegramBot, chat_id: int) -> None:
    ms = bot.bridge.memory_store if bot.bridge else None
    if not ms:
        bot._send_message(chat_id, "Memory not available.")
        return
    skills = ms.skill_list(str(chat_id))
    removed = 0
    for s in skills:
        if s["status"] == "inactive":
            ms.skill_remove(s["id"])
            removed += 1
    bot._send_message(chat_id, f"Removed {removed} inactive skills.")


# -- Jira action handlers ----------------------------------------------------

def _jira_workbench_code(code: str) -> str:
    """Wrap Python code for Composio REMOTE_WORKBENCH execution."""
    return code


def _parse_workbench_issues(stdout: str) -> list[dict]:
    """Extract issues list from workbench stdout output."""
    try:
        data = json.loads(stdout)
        # Handle nested: {"data": {"issues": [...]}} or just {"issues": [...]}
        if isinstance(data, dict):
            inner = data.get("data", data)
            if isinstance(inner, dict):
                return inner.get("issues") or []
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def _parse_jira_result(result: dict) -> list[dict]:
    """Parse issues from Composio workbench response."""
    try:
        content = result.get("content", [])
        if isinstance(content, list) and content:
            text = content[0].get("text", "{}")
            outer = json.loads(text)
            stdout = outer.get("data", {}).get("stdout", "")
            return _parse_workbench_issues(stdout)
    except (json.JSONDecodeError, KeyError, IndexError):
        pass
    return []


def _parse_jira_single(result: dict) -> dict | None:
    """Parse single issue from JIRA_GET_ISSUE workbench response.

    Response shape:
    {"data": {"key": "...", "fields": {"summary": "...", "description": "...", ...}, ...}}
    Normalizes by promoting fields.* to top level.
    """
    try:
        content = result.get("content", [])
        if isinstance(content, list) and content:
            text = content[0].get("text", "{}")
            outer = json.loads(text)
            stdout = outer.get("data", {}).get("stdout", "{}")
            data = json.loads(stdout)
            if isinstance(data, dict):
                inner = data.get("data", data)
                if isinstance(inner, dict) and inner.get("key"):
                    fields = inner.get("fields") or {}
                    if isinstance(fields, dict):
                        for k, v in fields.items():
                            if k not in inner:
                                inner[k] = v
                    return inner
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        pass
    return None


def _adf_to_plaintext(node: dict | list | str, indent: str = "") -> str:
    """Convert Atlassian Document Format (ADF) JSON to plain text."""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(_adf_to_plaintext(n, indent) for n in node)
    if not isinstance(node, dict):
        return str(node)
    node_type = node.get("type", "")
    content = node.get("content", [])
    text = node.get("text", "")
    marks = node.get("marks", [])

    if node_type == "doc":
        return _adf_to_plaintext(content, indent).strip()
    if node_type == "paragraph":
        return _adf_to_plaintext(content, indent) + "\n"
    if node_type == "heading":
        level = node.get("attrs", {}).get("level", 1)
        prefix = "#" * level + " "
        return prefix + _adf_to_plaintext(content, indent) + "\n"
    if node_type == "orderedList":
        order = node.get("attrs", {}).get("order", 1)
        lines = []
        for i, item in enumerate(content):
            lines.append(indent + f"{order + i}. " + _adf_to_plaintext(item.get("content", []), indent + "  ").lstrip())
        return "\n".join(lines) + "\n"
    if node_type == "bulletList":
        lines = []
        for item in content:
            lines.append(indent + "• " + _adf_to_plaintext(item.get("content", []), indent + "  ").lstrip())
        return "\n".join(lines) + "\n"
    if node_type == "listItem":
        return _adf_to_plaintext(content, indent)
    if node_type == "text":
        for m in marks:
            if m.get("type") == "link":
                href = m.get("attrs", {}).get("href", "")
                return f"[{text}]({href})"
        return text
    if node_type in ("hardBreak", "rule"):
        return "\n"
    if node_type == "inlineCard":
        return node.get("attrs", {}).get("url", "")
    if node_type == "mention":
        return f"@{node.get('attrs', {}).get('text', '')}"
    if node_type == "emoji":
        return node.get("attrs", {}).get("text", "")
    if node_type == "table":
        rows = []
        for row in content:
            cells = []
            for cell in (row.get("content") or []):
                cells.append(_adf_to_plaintext(cell.get("content", []), "").strip())
            rows.append(" | ".join(cells))
        return "\n".join(rows) + "\n"
    if node_type in ("tableRow", "tableHeader", "tableCell"):
        return _adf_to_plaintext(content, indent)
    # Fallback: recurse into content
    if content:
        return _adf_to_plaintext(content, indent)
    if text:
        return text
    return ""

async def _action_jira_open_tasks(bot: TelegramBot, chat_id: int) -> None:
    """Show open tasks from configured JIRA_EPICS via Composio workbench."""
    epics = getattr(bot, "jira_epics", [])
    if not epics:
        bot._send_message(chat_id, "⚠️ JIRA_EPICS not configured.\n\nSet the env var:\nJIRA_EPICS = PROJ-123,PROJ-456")
        return
    epic_list = ",".join(f'"{e}"' for e in epics)
    jql = f'"Epic Link" IN ({epic_list}) AND status IN ("To Do","In Progress") ORDER BY status DESC, priority DESC'
    code = (
        "import json\n"
        "result, err = run_composio_tool(\"JIRA_SEARCH_FOR_ISSUES_USING_JQL_GET\", "
        f'{{"jql": {json.dumps(jql)}, "fields": ["summary","status","assignee","issuetype","priority"], "max_results": 100}})\n'
        "if err:\n"
        '    print(json.dumps({{"error": str(err)}}))\n'
        "else:\n"
        "    print(json.dumps(result))\n"
    )
    result = await _call_composio(bot, "COMPOSIO_REMOTE_WORKBENCH", {"code_to_execute": code})
    if "error" in result:
        bot._send_message(chat_id, f"❌ {result['error']}")
        return
    # Parse workbench response — retry once on empty (workbench cold-start)
    issues = _parse_jira_result(result)
    if not issues:
        await asyncio.sleep(2)
        result = await _call_composio(bot, "COMPOSIO_REMOTE_WORKBENCH", {"code_to_execute": code})
        if "error" not in result:
            issues = _parse_jira_result(result)
    if not issues:
        kb = {"inline_keyboard": [
            [{"text": "🔄 Refresh", "callback_data": "ac:jira_open_tasks"},
             {"text": "🔙 Back", "callback_data": "mn:main"}]
        ]}
        bot._send_message(chat_id, "📋 No open tasks found in the configured epics.", reply_markup=kb)
        return
    # Build inline keyboard rows — max 25 tasks, one per row
    kb_rows = []
    for issue in issues[:25]:
        key = issue.get("key", "?")
        summary = issue.get("summary") or key
        status_obj = issue.get("status") or {}
        status = status_obj.get("name") if isinstance(status_obj, dict) else str(status_obj)
        icon = "🟡" if status == "In Progress" else "🔵"
        kb_rows.append([{"text": f"{icon} {key}: {summary[:30]}", "callback_data": f"ac:jira_task:{key}"}])
    kb_rows.append([
        {"text": "🔄 Refresh", "callback_data": "ac:jira_open_tasks"},
        {"text": "🔙 Back", "callback_data": "mn:main"},
    ])
    bot._send_message(chat_id, f"📋 Open Tasks ({len(issues)} total)", reply_markup={"inline_keyboard": kb_rows})


async def _action_jira_subtasks(bot: TelegramBot, chat_id: int, issue_key: str) -> None:
    """Show subtasks for a given issue via Composio workbench."""
    bot._subtask_parents[chat_id] = issue_key
    jql = f"parent = {issue_key} AND status IN ('To Do','In Progress') ORDER BY status DESC, priority DESC"
    code = (
        "import json\n"
        "result, err = run_composio_tool(\"JIRA_SEARCH_FOR_ISSUES_USING_JQL_GET\", "
        f'{{"jql": {json.dumps(jql)}, "fields": ["summary","status","assignee","issuetype","priority"], "max_results": 100}})\n'
        "if err:\n"
        '    print(json.dumps({{"error": str(err)}}))\n'
        "else:\n"
        "    print(json.dumps(result))\n"
    )
    result = await _call_composio(bot, "COMPOSIO_REMOTE_WORKBENCH", {"code_to_execute": code})
    if "error" in result:
        bot._send_message(chat_id, f"❌ {result['error']}")
        return
    issues = _parse_jira_result(result)
    if not issues:
        await asyncio.sleep(2)
        result = await _call_composio(bot, "COMPOSIO_REMOTE_WORKBENCH", {"code_to_execute": code})
        if "error" not in result:
            issues = _parse_jira_result(result)
    if not issues:
        kb = {"inline_keyboard": [[{"text": "🔙 Back", "callback_data": "ac:jira_open_tasks"}]]}
        bot._send_message(chat_id, f"📄 {issue_key}: No subtasks found.", reply_markup=kb)
        return
    header = f"📄 {issue_key} — Subtasks ({len(issues)} total)\n"
    kb_rows = []
    for sub in issues[:25]:
        key = sub.get("key", "?")
        summary = sub.get("summary") or key
        status_obj = sub.get("status") or {}
        status = status_obj.get("name") if isinstance(status_obj, dict) else str(status_obj)
        icon = "✅" if status == "Done" else ("🟡" if status == "In Progress" else "🔵")
        kb_rows.append([
            {"text": f"{icon} {key}: {summary[:80]}", "callback_data": f"ac:jira_show:{key}"},
            {"text": "▶️ Run", "callback_data": f"ac:jira_run:{key}"},
        ])
    if len(issues) > 25:
        header += f"\n...and {len(issues) - 25} more."
    kb_rows.append([
        {"text": "🔄 Refresh", "callback_data": f"ac:jira_task:{issue_key}"},
        {"text": "🔙 Back", "callback_data": "ac:jira_open_tasks"},
    ])
    bot._send_message(chat_id, header, reply_markup={"inline_keyboard": kb_rows})


async def _action_jira_show(bot: TelegramBot, chat_id: int, issue_key: str) -> None:
    """Fetch and display a single Jira issue's description (read-only view)."""
    code = (
        "import json\n"
        "result, err = run_composio_tool(\"JIRA_GET_ISSUE\", "
        f'{{"issue_key": {json.dumps(issue_key)}, "fields": ["description", "summary", "status", "assignee"]}})\n'
        "if err:\n"
        '    print(json.dumps({{"error": str(err)}}))\n'
        "else:\n"
        "    print(json.dumps(result))\n"
    )
    result = await _call_composio(bot, "COMPOSIO_REMOTE_WORKBENCH", {"code_to_execute": code})
    if "error" in result:
        bot._send_message(chat_id, f"❌ {result['error']}")
        return
    issue = _parse_jira_single(result)
    if not issue:
        await asyncio.sleep(2)
        result = await _call_composio(bot, "COMPOSIO_REMOTE_WORKBENCH", {"code_to_execute": code})
        if "error" not in result:
            issue = _parse_jira_single(result)
    if not issue:
        bot._send_message(chat_id, f"Could not fetch details for {issue_key}.")
        return
    summary = issue.get("summary") or issue_key
    desc = issue.get("description") or ""
    if isinstance(desc, dict):
        desc = _adf_to_plaintext(desc)
    elif isinstance(desc, str):
        try:
            parsed = json.loads(desc)
            if isinstance(parsed, dict):
                desc = _adf_to_plaintext(parsed)
        except json.JSONDecodeError:
            try:
                import ast
                parsed = ast.literal_eval(desc)
                if isinstance(parsed, dict):
                    desc = _adf_to_plaintext(parsed)
            except (ValueError, SyntaxError):
                pass
    if not desc:
        desc = "*No description.*"
    status_obj = issue.get("status") or {}
    status = status_obj.get("name") if isinstance(status_obj, dict) else str(status_obj)
    assignee_obj = issue.get("assignee") or {}
    assignee = assignee_obj.get("displayName", "Unassigned") if isinstance(assignee_obj, dict) else "Unassigned"
    status_icon = "✅" if status == "Done" else ("🟡" if status == "In Progress" else "🔵")
    text = f"📄 {issue_key}: {summary}\nStatus: {status_icon} {status} | Assignee: {assignee}\n\n{desc}"
    parent = bot._subtask_parents.get(chat_id, "")
    back_data = f"ac:jira_task:{parent}" if parent else "ac:jira_open_tasks"
    kb = {"inline_keyboard": [[{"text": "🔙 Back", "callback_data": back_data}]]}
    bot._send_message(chat_id, text[:4000], reply_markup=kb)


async def _action_jira_run(bot: TelegramBot, chat_id: int, issue_key: str) -> None:
    """Fetch Jira issue description and run it as an LLM prompt."""
    code = (
        "import json\n"
        "result, err = run_composio_tool(\"JIRA_GET_ISSUE\", "
        f'{{"issue_key": {json.dumps(issue_key)}, "fields": ["description", "summary", "status", "assignee"]}})\n'
        "if err:\n"
        '    print(json.dumps({{"error": str(err)}}))\n'
        "else:\n"
        "    print(json.dumps(result))\n"
    )
    bot._enqueue_typing(chat_id)
    result = await _call_composio(bot, "COMPOSIO_REMOTE_WORKBENCH", {"code_to_execute": code})
    if "error" in result:
        bot._send_message(chat_id, f"❌ {result['error']}")
        return
    issue = _parse_jira_single(result)
    if not issue:
        await asyncio.sleep(2)
        result = await _call_composio(bot, "COMPOSIO_REMOTE_WORKBENCH", {"code_to_execute": code})
        if "error" not in result:
            issue = _parse_jira_single(result)
    if not issue:
        bot._send_message(chat_id, f"Could not fetch details for {issue_key}.")
        return
    summary = issue.get("summary") or ""
    description = issue.get("description") or summary
    prompt = f"Execute this Jira task:\n\n{issue_key}: {summary}\n\n{description}"
    key = str(chat_id)
    history = bot._chat_history.setdefault(key, [])
    refresh = asyncio.create_task(bot._typing_refresher(chat_id))
    try:
        response = await asyncio.to_thread(bot.bridge_chat, prompt, history, key)
    finally:
        refresh.cancel()
        try:
            await refresh
        except asyncio.CancelledError:
            pass
    # Strip auto-learn skill wrapper if present (same pattern as _handle_message)
    if isinstance(response, str) and response.startswith('{"_skill_detected'):
        try:
            parsed = json.loads(response)
            response = parsed.get("response", "")
        except (json.JSONDecodeError, TypeError):
            pass
    history.extend([{"role": "user", "content": prompt}, {"role": "assistant", "content": response}])
    if len(history) > bot._history_max:
        bot._chat_history[key] = history[-bot._history_max:]
    bot._send_message(chat_id, response)


MENU_ACTIONS_ASYNC: dict[str, Callable] = {
    "web_status": _action_web_status,
    "memory_view": _action_memory_view,
    "memory_status": _action_memory_status,
    "memory_clear": _action_memory_clear,
    "memory_cleanup": _action_memory_cleanup,
    "chat_summarize": _action_chat_summarize,
    "voice_queue": _action_voice_queue,
    "tts_toggle": _action_tts_toggle,
    "system_status": _action_system_status,
    "system_provider": _action_system_provider,
    "system_uptime": _action_system_uptime,
    "system_queue": _action_system_queue,
    "system_composio": _action_system_composio,
    "schedule_add": _action_schedule_add,
    "schedule_list": _action_schedule_list,
    "skill_list": _action_skill_list,
    "skill_search_prompt": _action_skill_search_prompt,
    "skill_autolearn_toggle": _action_skill_autolearn_toggle,
    "skill_forget_inactive": _action_skill_forget_inactive,
    "jira_open_tasks": _action_jira_open_tasks,
}
