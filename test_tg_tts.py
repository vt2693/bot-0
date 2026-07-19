"""Tests for tg_tts module and telegram_bot TTS integration."""

import os
import asyncio
from unittest.mock import patch, MagicMock

import httpx
import pytest


# -- tg_tts.synthesize --------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_env():
    old = os.environ.pop("ROUTER_0_API_KEY", None)
    yield
    if old is not None:
        os.environ["ROUTER_0_API_KEY"] = old


def test_synthesize_returns_bytes():
    fake_mp3 = b"MP3_AUDIO_DATA..."
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.content = fake_mp3
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.Client") as MockClient:
        mock_client = MockClient.return_value.__enter__.return_value
        mock_client.post.return_value = mock_resp

        from tg_tts import synthesize
        result = synthesize("Hello world")

    assert result == fake_mp3
    call_kwargs = mock_client.post.call_args.kwargs
    assert call_kwargs["json"]["input"] == "Hello world"
    assert call_kwargs["json"]["model"] == "google-tts/en"
    # no voice or response_format params
    assert "voice" not in call_kwargs["json"]
    assert "response_format" not in call_kwargs["json"]


def test_synthesize_with_api_key():
    os.environ["ROUTER_0_API_KEY"] = "sk-test-key"
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.content = b"audio"
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.Client") as MockClient:
        mock_client = MockClient.return_value.__enter__.return_value
        mock_client.post.return_value = mock_resp

        from tg_tts import synthesize
        synthesize("Test")

    call_headers = mock_client.post.call_args.kwargs.get("headers", {})
    assert call_headers.get("Authorization") == "Bearer sk-test-key"


def test_synthesize_raises_on_http_error():
    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 400
    mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Bad Request", request=MagicMock(), response=mock_resp
    )

    with patch("httpx.Client") as MockClient:
        mock_client = MockClient.return_value.__enter__.return_value
        mock_client.post.return_value = mock_resp

        from tg_tts import synthesize
        with pytest.raises(httpx.HTTPStatusError):
            synthesize("Bad text")


def test_synthesize_raises_on_connection_error():
    with patch("httpx.Client") as MockClient:
        mock_client = MockClient.return_value.__enter__.return_value
        mock_client.post.side_effect = httpx.ConnectError("Connection refused")

        from tg_tts import synthesize
        with pytest.raises(httpx.RequestError):
            synthesize("Test")


# -- tg_tts.to_opus ----------------------------------------------------------

def test_to_opus_converts():
    fake_mp3 = b"FAKE_MP3"
    fake_opus = b"FAKE_OPUS_STREAM"
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            stdout=fake_opus, check_returncode=MagicMock()
        )
        from tg_tts import to_opus
        result = to_opus(fake_mp3)

    assert result == fake_opus
    assert "ffmpeg" in mock_run.call_args.args[0]
    assert mock_run.call_args.kwargs["input"] == fake_mp3


# -- telegram_bot._send_voice_direct ------------------------------------------

class FakeResponse:
    def __init__(self, ok: bool, status_code: int = 200):
        self._ok = ok
        self.status_code = status_code
    def json(self):
        return {"ok": self._ok}


def test_send_voice_direct_success():
    from telegram_bot import TelegramBot
    bot = TelegramBot("fake:token", lambda m, h, s: "reply", None)

    with patch("httpx.post") as mock_post, patch("time.sleep"):
        mock_post.return_value = FakeResponse(ok=True)

        result = bot._send_voice_direct(12345, b"fake_opus_bytes")

    assert result is True
    assert "api.telegram.org/bot" in mock_post.call_args.args[0]
    assert "/sendVoice" in mock_post.call_args.args[0]
    assert mock_post.call_args.kwargs["data"]["chat_id"] == 12345


def test_send_voice_direct_failure():
    from telegram_bot import TelegramBot
    bot = TelegramBot("fake:token", lambda m, h, s: "reply", None)

    with patch("httpx.post") as mock_post, patch("time.sleep"):
        mock_post.return_value = FakeResponse(ok=False)

        result = bot._send_voice_direct(12345, b"fake_opus_bytes")

    assert result is False


def test_send_voice_direct_network_error():
    from telegram_bot import TelegramBot
    bot = TelegramBot("fake:token", lambda m, h, s: "reply", None)

    with patch("httpx.post") as mock_post, patch("time.sleep"):
        mock_post.side_effect = httpx.ConnectError("timeout")

        result = bot._send_voice_direct(12345, b"fake_opus_bytes")

    assert result is False


# -- telegram_bot._action_tts_toggle ------------------------------------------

def test_tts_toggle_on():
    from telegram_bot import TelegramBot, _action_tts_toggle
    bot = TelegramBot("fake:token", lambda m, h, s: "reply", None)
    bot._tts_chats.discard(42)
    bot.bridge = MagicMock()
    bot.bridge.memory_store = None

    with patch.object(bot, "_send_message") as mock_send:
        asyncio.run(_action_tts_toggle(bot, 42))

    assert 42 in bot._tts_chats
    mock_send.assert_called_once()
    assert "ON" in mock_send.call_args[0][1]


def test_tts_toggle_off():
    from telegram_bot import TelegramBot, _action_tts_toggle
    bot = TelegramBot("fake:token", lambda m, h, s: "reply", None)
    bot._tts_chats.add(42)
    bot.bridge = MagicMock()
    bot.bridge.memory_store = None

    with patch.object(bot, "_send_message") as mock_send:
        asyncio.run(_action_tts_toggle(bot, 42))

    assert 42 not in bot._tts_chats
    mock_send.assert_called_once()
    assert "OFF" in mock_send.call_args[0][1]


# -- telegram_bot._send_tts_async --------------------------------------------

def test_send_tts_async_happy_path():
    from telegram_bot import TelegramBot
    bot = TelegramBot("fake:token", lambda m, h, s: "reply", None)
    bot.token = "test:token"
    fake_mp3 = b"MP3_AUDIO_DATA"
    fake_opus = b"OPUS_AUDIO_DATA"

    with patch("tg_tts.synthesize", return_value=fake_mp3) as mock_tts:
        with patch("tg_tts.to_opus", return_value=fake_opus) as mock_conv:
            with patch.object(bot, "_send_voice_direct", return_value=True) as mock_send:
                asyncio.run(bot._send_tts_async(42, "Hello world"))

    mock_tts.assert_called_once_with("Hello world")
    mock_conv.assert_called_once_with(fake_mp3)
    mock_send.assert_called_once_with(42, fake_opus)


def test_send_tts_async_empty_text():
    from telegram_bot import TelegramBot
    bot = TelegramBot("fake:token", lambda m, h, s: "reply", None)

    with patch("tg_tts.synthesize") as mock_tts:
        with patch.object(bot, "_send_voice_direct") as mock_send:
            asyncio.run(bot._send_tts_async(42, "   "))

    mock_tts.assert_not_called()
    mock_send.assert_not_called()


def test_send_tts_async_synthesize_fails():
    from telegram_bot import TelegramBot
    bot = TelegramBot("fake:token", lambda m, h, s: "reply", None)

    with patch("tg_tts.synthesize", side_effect=RuntimeError("Router down")):
        with patch.object(bot, "_send_voice_direct") as mock_send:
            asyncio.run(bot._send_tts_async(42, "Hello"))

    mock_send.assert_not_called()
