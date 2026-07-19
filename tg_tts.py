"""TTS helpers for Hermes Agent — synthesize speech via local router-0."""

import os
import subprocess
import tempfile
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


def to_video_note(mp3_bytes: bytes) -> bytes:
    """Convert MP3 bytes to a video note MP4 (360×360 black canvas + audio).

    Telegram video notes auto-play on arrival. Uses ffmpeg with a temporary
    file for video output so that +faststart moov repositioning is possible
    (requires a seekable output — pipe cannot provide this).

    Args:
        mp3_bytes: Raw MP3 audio bytes.

    Returns:
        Raw fast-start MP4 bytes suitable for Telegram sendVideoNote.

    Raises:
        subprocess.CalledProcessError: On ffmpeg failure.
        OSError: On temp-file creation failure.
    """
    # Write mp3 to temp file first — needed for ffprobe (seekable) and ffmpeg input
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as fin:
        fin.write(mp3_bytes)
        mp3_path = fin.name
    mp4_path = mp3_path.replace(".mp3", ".mp4")
    try:
        # Probe the temp file for audio duration
        duration_s = 10  # safe fallback
        try:
            probe = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", mp3_path],
                capture_output=True, timeout=15,
            )
            import json
            info = json.loads(probe.stdout)
            if "format" in info and "duration" in info["format"]:
                d = float(info["format"]["duration"])
                if d > 0:
                    duration_s = int(d) + 1
        except Exception:
            pass

        proc = subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", f"color=c=black:s=25x25:r=1:duration={duration_s}",
                "-i", mp3_path,
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-shortest",
                "-movflags", "+faststart",
                mp4_path,
            ],
            capture_output=True,
            timeout=60,
        )
        proc.check_returncode()
        with open(mp4_path, "rb") as f:
            return f.read()
    finally:
        try:
            os.unlink(mp3_path)
        except Exception:
            pass
        try:
            os.unlink(mp4_path)
        except Exception:
            pass
