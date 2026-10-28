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

    async def test_photo_caption_and_pending_image_followup(self):
        await self.bot.process_update({"message": {
            "chat": {"id": 42}, "from": {"id": 7}, "caption": "What is here?",
            "photo": [{"file_id": "small", "file_size": 10}, {"file_id": "large", "file_size": 20}],
        }})
        self.assertEqual(self.bridge.calls[0][:3], ("Describe this image briefly. Caption: What is here?", b"large.jpg", "image/jpeg"))
        self.assertIn("What would you like me to do with it?", self.messages[-1][1])
        await self.bot.process_update({"message": {"chat": {"id": 42}, "from": {"id": 7}, "text": "Read the sign"}})
        self.assertEqual(self.bridge.calls[1][:3], ("Read the sign", b"large.jpg", "image/jpeg"))
        self.assertNotIn(42, self.bot._pending_images)

    async def test_new_image_replaces_pending_and_command_does_not_consume(self):
        for file_id in ("first", "newest"):
            await self.bot.process_update({"message": {"chat": {"id": 42}, "from": {"id": 7}, "photo": [{"file_id": file_id}]}})
        self.assertEqual(self.bot._pending_images[42]["data"], b"newest.jpg")
        await self.bot.process_update({"message": {"chat": {"id": 42}, "from": {"id": 7}, "text": "/help"}})
        self.assertIn(42, self.bot._pending_images)
        self.assertEqual(len(self.bridge.calls), 2)

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

    async def test_failed_followup_retains_image_and_start_clears(self):

        self.bridge.fail = True
        await self.bot.process_update({"message": {"chat": {"id": 9}, "from": {"id": 1}, "photo": [{"file_id": "image"}]}})
        await self.bot.process_update({"message": {"chat": {"id": 9}, "from": {"id": 1}, "text": "Explain"}})
        self.assertIn(9, self.bot._pending_images)
        self.assertTrue(any("temporarily unavailable" in text for _, text in self.messages))
        await self.bot.process_update({"message": {"chat": {"id": 9}, "from": {"id": 1}, "text": "/start"}})
        self.assertNotIn(9, self.bot._pending_images)

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
