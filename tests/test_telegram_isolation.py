import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from memory_store import MemoryStore
from telegram_bot import MENU_ACTIONS_ASYNC, TelegramBot


class RecordingBot(TelegramBot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.callbacks_seen = []

    async def _handle_callback(self, callback):
        self.callbacks_seen.append(callback)


class TelegramIsolationCharacterizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_message_uses_sender_scope(self):
        calls = []

        def bridge_chat(message, history, scope):
            calls.append((message, history, scope))
            return "reply"

        bot = TelegramBot("token", bridge_chat, allowed_users="101")
        bot._initialized = True

        await bot.process_update(
            {
                "update_id": 1,
                "message": {
                    "from": {"id": 101},
                    "chat": {"id": 202, "type": "private"},
                    "text": "hello there",
                },
            }
        )

        self.assertEqual(calls[-1][2], "user:101")

    async def test_direct_message_handler_requires_explicit_scope(self):
        calls = []

        def bridge_chat(message, history, scope):
            calls.append(scope)
            return "reply"

        bot = TelegramBot("token", bridge_chat, allowed_users="101")
        bot._initialized = True

        with self.assertRaises(ValueError):
            await bot._handle_message(202, "direct call")

        self.assertEqual(calls, [])

    async def test_group_message_uses_chat_scope(self):
        calls = []

        def bridge_chat(message, history, scope):
            calls.append((message, history, scope))
            return "reply"

        bot = TelegramBot("token", bridge_chat, allowed_users="101")
        bot._initialized = True

        await bot.process_update(
            {
                "update_id": 4,
                "message": {
                    "from": {"id": 101},
                    "chat": {"id": -202, "type": "group"},
                    "text": "hello group",
                },
            }
        )

        self.assertEqual(calls[-1][2], "chat:-202")

    async def test_callback_from_unauthorized_user_is_rejected(self):
        bot = RecordingBot("token", lambda *_args: "reply", allowed_users="101")
        bot._initialized = True

        await bot.process_update(
            {
                "update_id": 2,
                "callback_query": {
                    "id": "callback-1",
                    "from": {"id": 999},
                    "message": {"chat": {"id": 202}, "message_id": 3},
                    "data": "mn:main",
                },
            }
        )

        self.assertEqual(bot.callbacks_seen, [])
        self.assertEqual(await bot.peek_outbox(), [])

    async def test_skill_list_menu_action_uses_chat_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = MemoryStore(str(Path(tmp) / "memory.db"))
            store.skill_add("Visible", "problem", "procedure", scope="chat:202")
            store.skill_add("Hidden", "problem", "procedure", scope="chat:303")
            bot = TelegramBot("token", lambda *_args: "reply")
            bot.bridge = SimpleNamespace(memory_store=store)
            bot._chat_scopes[202] = "chat:202"

            await MENU_ACTIONS_ASYNC["skill_list"](bot, 202)

            messages = await bot.peek_outbox()
            self.assertEqual(len(messages), 1)
            self.assertIn("Visible", messages[0]["text"])
            self.assertNotIn("Hidden", messages[0]["text"])
            store.close()

    def test_admin_user_list_accepts_comma_space_and_ignores_invalid_tokens(self):
        bot = TelegramBot(
            "token",
            lambda *_args: "reply",
            allowed_users="101, 202 303",
            admin_users=" 202,303 303 invalid -404 0 ",
        )

        self.assertEqual(bot.allowed_ids, {101, 202, 303})
        self.assertEqual(bot.admin_ids, {0, 202, 303})

    def test_admin_requires_authorized_user_when_allowlist_is_configured(self):
        bot = TelegramBot(
            "token",
            lambda *_args: "reply",
            allowed_users="101",
            admin_users="101,202",
        )

        self.assertTrue(bot._is_admin_user(101))
        self.assertFalse(bot._is_admin_user(202))
        self.assertFalse(bot._is_admin_user(None))

    def test_admin_allowlist_is_independent_when_users_are_unrestricted(self):
        bot = TelegramBot(
            "token",
            lambda *_args: "reply",
            allowed_users="",
            admin_users="202",
        )

        self.assertTrue(bot._is_authorized_user(101))
        self.assertTrue(bot._is_admin_user(202))
        self.assertFalse(bot._is_admin_user(101))

    async def test_non_admin_cannot_add_global_fact(self):
        store = MemoryStore(":memory:")
        bot = TelegramBot("token", lambda *_args: "reply", bridge=SimpleNamespace(memory_store=store), allowed_users="101", admin_users="202")
        bot._initialized = True
        await bot.process_update({"update_id": 8, "message": {"from": {"id": 101}, "chat": {"id": 202, "type": "private"}, "text": "/global add fact secret"}})
        self.assertEqual(store.search("secret", "global"), [])
        store.close()

    async def test_admin_global_fact_requires_confirmation(self):
        store = MemoryStore(":memory:")
        bot = TelegramBot("token", lambda *_args: "reply", bridge=SimpleNamespace(memory_store=store), allowed_users="202", admin_users="202")
        bot._initialized = True
        await bot.process_update({"update_id": 9, "message": {"from": {"id": 202}, "chat": {"id": 202, "type": "private"}, "text": "/global add fact shared"}})
        self.assertEqual(store.search("shared", "global"), [])
        messages = await bot.peek_outbox()
        callback_data = messages[-1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
        await bot.process_update({"update_id": 10, "callback_query": {"id": "cb", "from": {"id": 202}, "message": {"chat": {"id": 202, "type": "private"}, "message_id": 1}, "data": callback_data}})
        self.assertEqual(len(store.search("shared", "global")), 1)
        store.close()

    async def test_global_skill_actions_require_matching_admin_confirmation(self):
        store = MemoryStore(":memory:")
        skill_id = store.global_skill_add("Shared skill", "problem", "procedure")["id"]
        bot = TelegramBot("token", lambda *_args: "reply", bridge=SimpleNamespace(memory_store=store), allowed_users="202 303", admin_users="202")
        bot._initialized = True

        await bot.process_update({"update_id": 11, "message": {"from": {"id": 202}, "chat": {"id": 202, "type": "private"}, "text": f"/global disable skill {skill_id}"}})
        messages = await bot.peek_outbox()
        callback_data = messages[-1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
        await bot.process_update({"update_id": 12, "callback_query": {"id": "cb1", "from": {"id": 202}, "message": {"chat": {"id": 202, "type": "private"}, "message_id": 1}, "data": callback_data}})
        self.assertEqual(store.skill_get(skill_id, "global")["status"], "inactive")

        skill_id = store.global_skill_add("Another shared skill", "problem", "procedure")["id"]
        await bot.process_update({"update_id": 13, "message": {"from": {"id": 202}, "chat": {"id": 202, "type": "private"}, "text": f"/global disable skill {skill_id}"}})
        messages = await bot.peek_outbox()
        callback_data = messages[-1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
        await bot.process_update({"update_id": 14, "callback_query": {"id": "cb2", "from": {"id": 303}, "message": {"chat": {"id": 202, "type": "private"}, "message_id": 1}, "data": callback_data}})
        self.assertEqual(store.skill_get(skill_id, "global")["status"], "unverified")

        skill_id = store.global_skill_add("Expired shared skill", "problem", "procedure")["id"]
        await bot.process_update({"update_id": 15, "message": {"from": {"id": 202}, "chat": {"id": 202, "type": "private"}, "text": f"/global disable skill {skill_id}"}})
        messages = await bot.peek_outbox()
        callback_data = messages[-1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
        token = callback_data.rsplit(":", 1)[-1]
        bot._pending_skills[token]["expires_at"] = 0
        await bot.process_update({"update_id": 16, "callback_query": {"id": "cb3", "from": {"id": 202}, "message": {"chat": {"id": 202, "type": "private"}, "message_id": 1}, "data": callback_data}})
        self.assertEqual(store.skill_get(skill_id, "global")["status"], "unverified")
        store.close()

    async def test_callback_from_authorized_user_is_routed(self):
        bot = RecordingBot("token", lambda *_args: "reply", allowed_users="101")
        bot._initialized = True

        await bot.process_update(
            {
                "update_id": 3,
                "callback_query": {
                    "id": "callback-2",
                    "from": {"id": 101},
                    "message": {"chat": {"id": 202}, "message_id": 4},
                    "data": "mn:main",
                },
            }
        )

        self.assertEqual(len(bot.callbacks_seen), 1)
        self.assertEqual(bot.callbacks_seen[0]["from"]["id"], 101)


if __name__ == "__main__":
    unittest.main()
