import base64
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import telegram_bot
from config import Settings
from hermes_bridge import HermesBridge
from telegram_bot import TelegramBot


class VisionBridge:
    def __init__(self, responses=None, fail=False):
        self.calls = []
        self.responses = list(responses or ["A cat on a chair."])
        self.fail = fail

    def chat_with_image(self, text, image, mime_type, history=None):
        self.calls.append((text, image, mime_type, history))
        if self.fail:
            raise RuntimeError("provider unavailable")
        return self.responses.pop(0)

    def chat_with_images(self, text, images, history=None):
        self.calls.append((text, images, history))
        if self.fail:
            raise RuntimeError("provider unavailable")
        return self.responses.pop(0)


class TelegramImageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bridge = VisionBridge(["A cat on a chair.", "The cat is orange."])
        self.bot = TelegramBot("token", lambda *args: "text response", bridge=self.bridge)
        self.messages = []
        self.bot._send_message = lambda chat_id, text, **kwargs: self.messages.append((chat_id, text))
        self.work_dir = patch.dict("os.environ", {"WORK_DIR": self.temp.name})
        self.work_dir.start()
        self.addCleanup(self.work_dir.stop)
        self.get_path = patch.object(telegram_bot, "tg_file_path", side_effect=lambda token, file_id: f"{file_id}.jpg")
        self.get_path.start()
        self.addCleanup(self.get_path.stop)
        self.download = patch.object(telegram_bot, "download_file", side_effect=lambda token, path, out: out.write_bytes(path.encode()))
        self.download.start()
        self.addCleanup(self.download.stop)

    async def test_multiple_uploads_wait_for_explicit_analysis_and_retain_batch(self):
        for file_id, caption in (("first", "front"), ("second", "back")):
            await self.bot.process_update({"message": {
                "chat": {"id": 42}, "from": {"id": 7}, "caption": caption,
                "photo": [{"file_id": file_id}],
            }})

        self.assertEqual(self.bridge.calls, [])
        self.assertEqual(
            [(item["data"], item["caption"]) for item in self.bot._pending_images[42]],
            [(b"first.jpg", "front"), (b"second.jpg", "back")],
        )

        await self.bot.process_update({"message": {
            "chat": {"id": 42}, "from": {"id": 7}, "text": "/analyze Compare them",
        }})
        self.assertEqual(self.bridge.calls[0][0], "Compare them")
        self.assertEqual([item["caption"] for item in self.bridge.calls[0][1]], ["front", "back"])
        self.assertEqual(len(self.bot._pending_images[42]), 2)
        self.assertIn("What would you like to do next?", self.messages[-1][1])

    async def test_photo_upload_queues_caption_without_analysis(self):
        await self.bot.process_update({"message": {
            "chat": {"id": 42}, "from": {"id": 7}, "caption": "What is here?",
            "photo": [{"file_id": "small", "file_size": 10}, {"file_id": "large", "file_size": 20}],
        }})
        self.assertEqual(self.bridge.calls, [])
        self.assertEqual(self.bot._pending_images[42][0], {
            "data": b"large.jpg", "mime_type": "image/jpeg", "caption": "What is here?",
        })
        self.assertIn("queued", self.messages[-1][1].lower())
        await self.bot.process_update({"message": {"chat": {"id": 42}, "from": {"id": 7}, "text": "Read the sign"}})
        self.assertEqual(self.bridge.calls, [])
        self.assertEqual(len(self.bot._pending_images[42]), 1)
        self.assertEqual(self.messages[-1][1], "text response")

    async def test_analyze_retains_images_for_reanalysis_and_start_preserves_them(self):
        await self.bot.process_update({"message": {"chat": {"id": 9}, "from": {"id": 1}, "photo": [{"file_id": "image"}]}})
        await self.bot.process_update({"message": {"chat": {"id": 9}, "from": {"id": 1}, "text": "/analyze@hermesbot"}})
        self.assertEqual(len(self.bridge.calls), 1)
        self.assertEqual(len(self.bot._pending_images[9]), 1)
        self.assertIn("What would you like to do next?", self.messages[-1][1])
        await self.bot.process_update({"message": {"chat": {"id": 9}, "from": {"id": 1}, "text": "/start"}})
        self.assertEqual(len(self.bot._pending_images[9]), 1)
        await self.bot.process_update({"message": {"chat": {"id": 9}, "from": {"id": 1}, "text": "/analyze Another question"}})
        self.assertEqual(len(self.bridge.calls), 2)
        self.assertEqual(self.bridge.calls[-1][0], "Another question")
        self.assertEqual(len(self.bot._pending_images[9]), 1)

    async def test_empty_analysis_and_clear_commands(self):
        await self.bot.process_update({"message": {"chat": {"id": 3}, "from": {"id": 1}, "text": "/analyze"}})
        self.assertEqual(self.bridge.calls, [])
        self.assertIn("no images", self.messages[-1][1].lower())
        await self.bot.process_update({"message": {"chat": {"id": 3}, "from": {"id": 1}, "photo": [{"file_id": "image"}]}})
        await self.bot.process_update({"message": {"chat": {"id": 3}, "from": {"id": 1}, "text": "/clear_images@hermesbot"}})
        self.assertNotIn(3, self.bot._pending_images)

    async def test_batch_limit_rejects_eleventh_without_dropping_accepted_images(self):
        for i in range(11):
            await self.bot.process_update({"message": {"chat": {"id": 5}, "from": {"id": 1}, "photo": [{"file_id": str(i)}]}})
        self.assertEqual(len(self.bot._pending_images[5]), 10)
        self.assertEqual(self.bot._pending_images[5][0]["data"], b"0.jpg")
        self.assertIn("10", self.messages[-1][1])

    async def test_failed_analysis_retains_batch_and_new_upload_starts_fresh_after_success(self):
        await self.bot.process_update({"message": {"chat": {"id": 6}, "from": {"id": 1}, "photo": [{"file_id": "first"}]}})
        self.bridge.fail = True
        await self.bot.process_update({"message": {"chat": {"id": 6}, "from": {"id": 1}, "text": "/analyze"}})
        self.assertEqual(len(self.bot._pending_images[6]), 1)
        self.bridge.fail = False
        await self.bot.process_update({"message": {"chat": {"id": 6}, "from": {"id": 1}, "text": "/analyze"}})
        await self.bot.process_update({"message": {"chat": {"id": 6}, "from": {"id": 1}, "photo": [{"file_id": "second"}]}})
        self.assertEqual([x["data"] for x in self.bot._pending_images[6]], [b"second.jpg"])

    async def test_unauthorized_callback_cannot_clear_batch(self):
        self.bot.allowed_ids = {7}
        self.bot._pending_images[42] = [{"data": b"kept", "mime_type": "image/jpeg", "caption": ""}]
        await self.bot.process_update({"callback_query": {
            "id": "cb", "from": {"id": 99}, "data": "ac:images_clear",
            "message": {"chat": {"id": 42}, "message_id": 10},
        }})
        self.assertIn(42, self.bot._pending_images)
        self.assertNotIn((42, "Images cleared."), self.messages)

    async def test_new_upload_starts_fresh_even_when_analyzed_batch_is_full(self):
        for i in range(10):
            await self.bot.process_update({"message": {"chat": {"id": 24}, "from": {"id": 1}, "photo": [{"file_id": str(i)}]}})
        await self.bot.process_update({"message": {"chat": {"id": 24}, "from": {"id": 1}, "text": "/analyze"}})
        await self.bot.process_update({"message": {"chat": {"id": 24}, "from": {"id": 1}, "photo": [{"file_id": "fresh"}]}})
        self.assertEqual([x["data"] for x in self.bot._pending_images[24]], [b"fresh.jpg"])

    async def test_new_upload_starts_fresh_even_when_analyzed_batch_is_full(self):
        for i in range(10):
            await self.bot.process_update({"message": {"chat": {"id": 24}, "from": {"id": 1}, "photo": [{"file_id": str(i)}]}})
        await self.bot.process_update({"message": {"chat": {"id": 24}, "from": {"id": 1}, "text": "/analyze"}})
        await self.bot.process_update({"message": {"chat": {"id": 24}, "from": {"id": 1}, "photo": [{"file_id": "fresh"}]}})
        self.assertEqual([x["data"] for x in self.bot._pending_images[24]], [b"fresh.jpg"])

    async def test_new_upload_starts_fresh_batch_after_analysis(self):
        for file_id in ("first", "newest"):
            await self.bot.process_update({"message": {"chat": {"id": 42}, "from": {"id": 7}, "photo": [{"file_id": file_id}]}})
        self.assertEqual([x["data"] for x in self.bot._pending_images[42]], [b"first.jpg", b"newest.jpg"])
        await self.bot.process_update({"message": {"chat": {"id": 42}, "from": {"id": 7}, "text": "/help"}})
        self.assertEqual(self.bridge.calls, [])
        await self.bot.process_update({"message": {"chat": {"id": 42}, "from": {"id": 7}, "text": "/analyze"}})
        self.assertEqual(len(self.bot._pending_images[42]), 2)
        await self.bot.process_update({"message": {"chat": {"id": 42}, "from": {"id": 7}, "photo": [{"file_id": "newer"}]}})
        self.assertEqual([x["data"] for x in self.bot._pending_images[42]], [b"newer.jpg"])

    async def test_chat_menu_contains_explicit_image_actions(self):
        callbacks = {button["callback_data"] for row in telegram_bot.MENUS["chat"]["buttons"] for button in row}
        self.assertIn("ac:images_analyze", callbacks)
        self.assertIn("ac:images_clear", callbacks)

    async def test_new_image_replaces_pending_and_command_does_not_consume(self):
        # The former single-image slot is now an ordered batch; ordinary commands leave it intact.
        for file_id in ("first", "newest"):
            await self.bot.process_update({"message": {"chat": {"id": 42}, "from": {"id": 7}, "photo": [{"file_id": file_id}]}})
        self.assertEqual([x["data"] for x in self.bot._pending_images[42]], [b"first.jpg", b"newest.jpg"])
        await self.bot.process_update({"message": {"chat": {"id": 42}, "from": {"id": 7}, "text": "/help"}})
        self.assertEqual(len(self.bot._pending_images[42]), 2)
        self.assertEqual(self.bridge.calls, [])

    async def test_analyze_callback_checks_callback_user(self):
        self.bot.allowed_ids = {7}
        self.bot._pending_images[42] = [{"data": b"kept", "mime_type": "image/jpeg", "caption": ""}]
        await self.bot.process_update({"callback_query": {
            "id": "cb", "from": {"id": 99}, "data": "ac:images_analyze",
            "message": {"chat": {"id": 42}, "message_id": 10},
        }})
        self.assertEqual(self.bridge.calls, [])
        self.assertEqual(len(self.bot._pending_images[42]), 1)

    async def test_menu_analysis_and_clear_callbacks(self):
        await self.bot.process_update({"message": {"chat": {"id": 21}, "from": {"id": 7}, "photo": [{"file_id": "one"}]}})
        await self.bot.process_update({"callback_query": {"id": "cb1", "from": {"id": 7}, "data": "ac:images_analyze", "message": {"chat": {"id": 21}, "message_id": 1}}})
        self.assertEqual(self.bridge.calls[0][0], "Analyze these images and describe their contents.")
        self.assertEqual(len(self.bot._pending_images[21]), 1)
        await self.bot.process_update({"callback_query": {"id": "cb2", "from": {"id": 7}, "data": "ac:images_clear", "message": {"chat": {"id": 21}, "message_id": 1}}})
        self.assertNotIn(21, self.bot._pending_images)
        self.assertIn("cleared", self.messages[-1][1].lower())

    async def test_failed_upload_preserves_existing_batch(self):
        await self.bot.process_update({"message": {"chat": {"id": 4}, "from": {"id": 1}, "photo": [{"file_id": "good"}]}})
        original = telegram_bot.download_file
        with patch.object(telegram_bot, "download_file", side_effect=lambda token, path, out: (_ for _ in ()).throw(OSError("network down")) if path == "bad.jpg" else original(token, path, out)):
            await self.bot.process_update({"message": {"chat": {"id": 4}, "from": {"id": 1}, "photo": [{"file_id": "bad"}]}})
        self.assertEqual([x["data"] for x in self.bot._pending_images[4]], [b"good.jpg"])

    async def test_command_registration_includes_analysis_commands(self):
        self.bot.configure_commands()
        commands = next(item["commands"] for item in self.bot.outbox if item.get("_method") == "setMyCommands")
        self.assertTrue({"analyze", "clear_images"}.issubset({item["command"] for item in commands}))

    async def test_image_document_and_pdf_routing(self):
        await self.bot.process_update({"message": {"chat": {"id": 1}, "from": {"id": 2}, "document": {"file_id": "img", "mime_type": "image/png"}}})
        self.assertEqual(self.bridge.calls[0][2], "image/png")
        called = []
        async def handle_document(chat_id, doc):
            called.append(doc)
        with patch.object(self.bot, "_handle_document", handle_document):
            await self.bot.process_update({"message": {"chat": {"id": 1}, "from": {"id": 2}, "document": {"file_id": "pdf", "mime_type": "application/pdf"}}})
        self.assertEqual(called, [{"file_id": "pdf", "mime_type": "application/pdf"}])

    async def test_unrecognized_document_is_not_sent_to_pdf_handler(self):
        called = []
        async def handle_document(chat_id, doc):
            called.append(doc)
        with patch.object(self.bot, "_handle_document", handle_document):
            await self.bot.process_update({"message": {"chat": {"id": 11}, "from": {"id": 1}, "document": {"file_id": "bin", "mime_type": "application/octet-stream"}}})
        self.assertEqual(called, [])
        self.assertTrue(any("only PDFs" in text for _, text in self.messages))

    async def test_failed_analysis_retains_image_and_start_preserves(self):
        await self.bot.process_update({"message": {"chat": {"id": 9}, "from": {"id": 1}, "photo": [{"file_id": "image"}]}})
        self.bridge.fail = True
        await self.bot.process_update({"message": {"chat": {"id": 9}, "from": {"id": 1}, "text": "/analyze Explain"}})
        self.assertIn(9, self.bot._pending_images)
        self.assertTrue(any("temporarily unavailable" in text for _, text in self.messages))
        await self.bot.process_update({"message": {"chat": {"id": 9}, "from": {"id": 1}, "text": "/start"}})
        self.assertIn(9, self.bot._pending_images)
        self.assertEqual(len(self.bot._pending_images[9]), 1)

    def test_multi_image_bridge_preserves_order_and_captions(self):
        bridge = HermesBridge(Settings())
        bridge._ready = True
        bridge._provider = "router_0"
        bridge._model = "vision-model"
        bridge._resolve_base_url = lambda: "http://localhost/v1"
        bridge._resolve_api_key = lambda: ""
        seen = {}

        class Response:
            def raise_for_status(self): pass
            def json(self): return {"choices": [{"message": {"content": "ok"}}]}

        def post(url, json, headers, timeout):
            seen.update(json)
            return Response()

        with patch("hermes_bridge.httpx.post", post):
            self.assertEqual(bridge.chat_with_images("compare", [
                {"data": b"one", "mime_type": "image/png", "caption": "front"},
                {"data": b"two", "mime_type": "image/jpeg", "caption": "back"},
            ]), "ok")
        content = seen["messages"][-1]["content"]
        self.assertEqual(content[0], {"type": "text", "text": "compare"})
        self.assertEqual(content[1], {"type": "text", "text": "front"})
        self.assertTrue(content[2]["image_url"]["url"].startswith("data:image/png;base64,"))
        self.assertEqual(content[3], {"type": "text", "text": "back"})
        self.assertTrue(content[4]["image_url"]["url"].startswith("data:image/jpeg;base64,"))
        self.assertEqual(seen["tools"], [])
        self.assertEqual(seen.get("tool_choice"), "none")

    async def test_oversized_and_missing_file_uploads_do_not_mutate_batch(self):
        await self.bot.process_update({"message": {"chat": {"id": 8}, "from": {"id": 1}, "photo": [{"file_id": "kept"}]}})
        await self.bot.process_update({"message": {"chat": {"id": 8}, "from": {"id": 1}, "photo": [{"file_id": "huge", "file_size": 11 * 1024 * 1024}]}})
        await self.bot.process_update({"message": {"chat": {"id": 8}, "from": {"id": 1}, "photo": [{"file_size": 20}]}})
        self.assertEqual([x["data"] for x in self.bot._pending_images[8]], [b"kept.jpg"])

    async def test_empty_batch_clear_reports_no_images(self):
        await self.bot.process_update({"message": {"chat": {"id": 12}, "from": {"id": 1}, "text": "/clear_images"}})
        self.assertIn("no images", self.messages[-1][1].lower())

    async def test_image_11_is_rejected_and_existing_images_survive_clear(self):
        for i in range(10):
            await self.bot.process_update({"message": {"chat": {"id": 15}, "from": {"id": 1}, "photo": [{"file_id": str(i)}]}})
        await self.bot.process_update({"message": {"chat": {"id": 15}, "from": {"id": 1}, "photo": [{"file_id": "overflow"}]}})
        self.assertEqual(len(self.bot._pending_images[15]), 10)
        self.assertEqual(self.bot._pending_images[15][0]["data"], b"0.jpg")
        self.assertIn("limit", self.messages[-1][1].lower())
        await self.bot.process_update({"message": {"chat": {"id": 15}, "from": {"id": 1}, "text": "/clear_images"}})
        self.assertNotIn(15, self.bot._pending_images)

    def test_chat_with_image_remains_compatible(self):
        bridge = HermesBridge(Settings())
        bridge._ready = True
        bridge._provider = "router_0"
        bridge._model = "vision-model"
        bridge._resolve_base_url = lambda: "http://localhost/v1"
        bridge._resolve_api_key = lambda: ""
        seen = {}

        class Response:
            def raise_for_status(self): pass
            def json(self): return {"choices": [{"message": {"content": "ok"}}]}

        with patch("hermes_bridge.httpx.post", lambda url, json, headers, timeout: (seen.update(json) or Response())):
            self.assertEqual(bridge.chat_with_image("legacy", b"abc", "image/png"), "ok")
        self.assertEqual(seen["messages"][-1]["content"][0], {"type": "text", "text": "legacy"})
        self.assertTrue(seen["messages"][-1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,"))

    async def test_regular_text_does_not_trigger_pending_image(self):
        await self.bot.process_update({"message": {"chat": {"id": 18}, "from": {"id": 1}, "photo": [{"file_id": "image"}]}})
        before = len(self.bridge.calls)
        await self.bot.process_update({"message": {"chat": {"id": 18}, "from": {"id": 1}, "text": "ordinary request"}})
        self.assertEqual(len(self.bridge.calls), before)
        self.assertEqual(len(self.bot._pending_images[18]), 1)

    async def test_failed_analysis_does_not_clear_batch(self):
        await self.bot.process_update({"message": {"chat": {"id": 19}, "from": {"id": 1}, "photo": [{"file_id": "image"}]}})
        self.bridge.fail = True
        await self.bot.process_update({"message": {"chat": {"id": 19}, "from": {"id": 1}, "text": "/analyze"}})
        self.assertEqual(len(self.bot._pending_images[19]), 1)

    async def test_analysis_updates_history(self):
        await self.bot.process_update({"message": {"chat": {"id": 20}, "from": {"id": 1}, "photo": [{"file_id": "image"}]}})
        await self.bot.process_update({"message": {"chat": {"id": 20}, "from": {"id": 1}, "text": "/analyze"}})
        self.assertEqual(self.bot._chat_history["20"][-2]["role"], "user")
        self.assertEqual(self.bot._chat_history["20"][-1]["role"], "assistant")

    async def test_command_group_suffix_and_default_prompt(self):
        await self.bot.process_update({"message": {"chat": {"id": 23}, "from": {"id": 1}, "photo": [{"file_id": "image"}]}})
        await self.bot.process_update({"message": {"chat": {"id": 23}, "from": {"id": 1}, "text": "/analyze@hermesbot"}})
        self.assertEqual(self.bridge.calls[-1][0], "Analyze these images and describe their contents.")
        await self.bot.process_update({"message": {"chat": {"id": 23}, "from": {"id": 1}, "text": "/clear_images@hermesbot"}})
        self.assertNotIn(23, self.bot._pending_images)

    async def test_serial_update_worker_awaits_each_update(self):
        self.assertIn("await self.process_update(item)", __import__("inspect").getsource(TelegramBot.process_queue_worker))

    async def test_image_document_and_pdf_routing(self):
        await self.bot.process_update({"message": {"chat": {"id": 1}, "from": {"id": 2}, "document": {"file_id": "img", "mime_type": "image/png"}}})
        self.assertEqual(self.bridge.calls, [])
        self.assertEqual(self.bot._pending_images[1][0]["mime_type"], "image/png")
        called = []
        async def handle_document(chat_id, doc):
            called.append(doc)
        with patch.object(self.bot, "_handle_document", handle_document):
            await self.bot.process_update({"message": {"chat": {"id": 1}, "from": {"id": 2}, "document": {"file_id": "pdf", "mime_type": "application/pdf"}}})
        self.assertEqual(called, [{"file_id": "pdf", "mime_type": "application/pdf"}])

    def test_image_request_does_not_fail_over_to_unverified_provider(self):
        bridge = HermesBridge(Settings())
        bridge._ready = True
        bridge._provider = "router_0"
        bridge._model = "vision-model"
        bridge.settings.LLM_RETRY_ATTEMPTS = 1
        bridge._resolve_base_url = lambda: "http://localhost/v1"
        bridge._resolve_api_key = lambda: ""
        bridge.settings.ROUTER_0_API_KEY = ""
        bridge.settings.OPENROUTER_API_KEY = "fallback-key"
        bridge.settings.OPENCODE_ZEN_API_KEY = ""
        bridge._try_failover = lambda primary: self.fail("image request attempted provider failover")
        class Response:
            def raise_for_status(self):
                raise __import__("httpx").HTTPStatusError("bad request", request=None, response=None)
        with patch("hermes_bridge.httpx.post", lambda *args, **kwargs: Response()):
            with self.assertRaises(__import__("httpx").HTTPStatusError):
                bridge.chat_with_image("describe", b"abc", "image/png")

    def test_bridge_builds_multimodal_data_url(self):
        bridge = HermesBridge(Settings())
        bridge._ready = True
        bridge._provider = "router_0"
        bridge._model = "vision-model"
        bridge._resolve_base_url = lambda: "http://localhost/v1"
        bridge._resolve_api_key = lambda: ""
        seen = {}
        class Response:
            def raise_for_status(self): pass
            def json(self): return {"choices": [{"message": {"content": "ok"}}]}
        def post(url, json, headers, timeout):
            seen.update(json)
            return Response()
        with patch("hermes_bridge.httpx.post", post):
            self.assertEqual(bridge.chat_with_image("describe", b"abc", "image/png"), "ok")
        content = seen["messages"][-1]["content"]
        self.assertEqual(content[0], {"type": "text", "text": "describe"})
        self.assertEqual(content[1]["image_url"]["url"], "data:image/png;base64," + base64.b64encode(b"abc").decode())


if __name__ == "__main__":
    unittest.main()
