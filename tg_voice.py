"""Voice helpers for Hermes Agent — download Telegram audio, transcribe via Groq/NVIDIA."""

import json
import subprocess
import urllib.request
from pathlib import Path


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
    parts.append(
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{wav.name}"\r\n'
        "Content-Type: audio/wav\r\n\r\n".encode()
    )
    parts.append(audio)
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        url,
        data=b"".join(parts),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode())
    return data.get("text") or data.get("transcript") or json.dumps(data)


def transcribe(wav: Path, groq_key: str = "", nvidia_key: str = "") -> str:
    """Transcribe WAV using Groq Whisper, fallback to NVIDIA."""
    if groq_key:
        return multipart_transcribe(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            groq_key, "whisper-large-v3", wav,
        )
    if nvidia_key:
        return multipart_transcribe(
            "https://integrate.api.nvidia.com/v1/audio/transcriptions",
            nvidia_key, "nvidia/parakeet-ctc-1.1b-asr", wav,
        )
    raise RuntimeError("No GROQ_API_KEY or NVIDIA_API_KEY set")
