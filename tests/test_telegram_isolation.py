import unittest

from telegram_bot import TelegramBot


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
