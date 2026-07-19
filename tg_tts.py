"""TTS helpers for Hermes Agent — synthesize speech via local router-0."""

import os
import subprocess
import logging

import httpx

_BASE = os.getenv("ROUTER_0_AUDIO_URL") or os.getenv("TTS_URL") or ""
TTS_URL = _BASE.rstrip("/") + "/audio/speech" if _BASE else ""
TTS_MODEL = os.getenv("TTS_MODEL", "edge-tts/en-US-AndrewMultilingualNeural")

logger = logging.getLogger(__name__)


def synthesize(text: str, voice: str = "", model: str = "") -> bytes:
    """Synthesize text to MP3 audio via router-0 TTS endpoint.

    Args:
        text: Text to speak (max ~4096 chars recommended).
        voice: Ignored for most models. Kept for compatibility.
        model: Override TTS_MODEL for this call.

    Returns:
        Raw MP3 audio bytes.

    Raises:
        httpx.HTTPStatusError: On non-2xx from router-0.
        httpx.RequestError: On network/connection failure.
    """
    api_key = os.getenv("ROUTER_0_API_KEY", "")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    body = {
        "model": model or TTS_MODEL,
        "input": text,
    }

    with httpx.Client(timeout=60.0) as client:
        resp = client.post(TTS_URL, json=body, headers=headers)
        resp.raise_for_status()
        return resp.content


def to_opus(mp3_bytes: bytes) -> bytes:
    """Convert MP3 bytes to OggOpus bytes via ffmpeg (pipe).

    Same pattern as tg_voice.to_wav but outputs OggOpus for Telegram sendVoice.
    """
    proc = subprocess.run(
        ["ffmpeg", "-y", "-i", "pipe:0", "-f", "ogg", "-codec:a", "libopus", "pipe:1"],
        input=mp3_bytes,
        capture_output=True,
        timeout=30,
    )
    proc.check_returncode()
    return proc.stdout

