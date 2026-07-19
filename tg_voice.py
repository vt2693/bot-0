"""Voice helpers for Hermes Agent — download Telegram audio, transcribe via local router-0."""

import json
import os
import subprocess
import urllib.request
from pathlib import Path

STT_URL = "http://localhost:20128/v1/audio/transcriptions"
STT_MODEL = "groq/whisper-large-v3"


def tg_file_path(bot_token: str, file_id: str) -> str:
    """Get Telegram file path from file_id."""
    url = f"https://api.telegram.org/bot{bot_token}/getFile?file_id={file_id}"
    with urllib.request.urlopen(url, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    return data["result"]["file_path"]


def download_file(bot_token: str, file_path: str, out: Path) -> None:
    """Download a Telegram file to disk."""
    url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
    with urllib.request.urlopen(url, timeout=60) as resp:
        out.write_bytes(resp.read())


def to_wav(src: Path) -> Path:
    """Convert audio to 16kHz mono WAV via ffmpeg."""
    dst = src.with_suffix(".wav")
    subprocess.check_call(
        ["ffmpeg", "-y", "-i", str(src), "-ar", "16000", "-ac", "1", str(dst)]
    )
    return dst


def multipart_transcribe(url: str, api_key: str, model: str, wav: Path) -> str:
    """Transcribe WAV via multipart POST to an OpenAI-compatible ASR endpoint."""
    boundary = "----HermesVoiceBoundary"
    audio = wav.read_bytes()
    parts = []
    def field(name, value):
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n".encode()
        )
    field("model", model)
    field("response_format", "json")
    parts.append(
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{wav.name}"\r\n'
        "Content-Type: audio/wav\r\n\r\n".encode()
    )
    parts.append(audio)
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(
        url,
        data=b"".join(parts),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode())
    return data.get("text") or data.get("transcript") or json.dumps(data)


def transcribe(wav: Path) -> str:
    """Transcribe WAV via local router-0 STT endpoint."""
    api_key = os.getenv("ROUTER_0_API_KEY", "")
    return multipart_transcribe(STT_URL, api_key, STT_MODEL, wav)
