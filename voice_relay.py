import os
import sys
import time
import json
import tempfile
import subprocess
import urllib.request
from pathlib import Path

print = lambda *a, **kw: __builtins__.print(*a, **kw, flush=True)  # noqa

SPACE_URL = os.getenv("SPACE_URL", "https://vt2693-bot-0.hf.space").rstrip("/")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "")
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "1"))
WORK_DIR = Path(os.getenv("WORK_DIR", tempfile.gettempdir()))
WORK_DIR.mkdir(parents=True, exist_ok=True)


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as resp:
        return json.loads(resp.read().decode())


def post_json(url: str, payload: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def tg_file_path(file_id: str) -> str:
    data = get_json(f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}")
    return data["result"]["file_path"]


def download_file(file_path: str, out: Path) -> None:
    url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_path}"
    with urllib.request.urlopen(url, timeout=60) as resp:
        out.write_bytes(resp.read())


def to_wav(src: Path) -> Path:
    dst = src.with_suffix(".wav")
    subprocess.check_call(["ffmpeg", "-y", "-i", str(src), "-ar", "16000", "-ac", "1", str(dst)])
    return dst


def multipart_transcribe(url: str, api_key: str, model: str, wav: Path) -> str:
    boundary = "----HermesVoiceBoundary"
    audio = wav.read_bytes()
    parts = []
    def field(name, value):
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
    field("model", model)
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{wav.name}\"\r\nContent-Type: audio/wav\r\n\r\n".encode())
    parts.append(audio); parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(url, data=b"".join(parts), headers={"Authorization": f"Bearer {api_key}", "Content-Type": f"multipart/form-data; boundary={boundary}"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode())
    return data.get("text") or data.get("transcript") or json.dumps(data)


def transcribe(wav: Path) -> str:
    if GROQ_API_KEY:
        return multipart_transcribe("https://api.groq.com/openai/v1/audio/transcriptions", GROQ_API_KEY, "whisper-large-v3", wav)
    if NVIDIA_API_KEY:
        return multipart_transcribe("https://integrate.api.nvidia.com/v1/audio/transcriptions", NVIDIA_API_KEY, "nvidia/parakeet-ctc-1.1b-asr", wav)
    raise RuntimeError("No GROQ_API_KEY or NVIDIA_API_KEY set")


def process(item: dict) -> None:
    chat_id = item["chat_id"]
    try:
        file_id = item["file_id"]
        path = tg_file_path(file_id)
        src = WORK_DIR / ("voice_" + file_id.replace(":", "_") + Path(path).suffix)
        download_file(path, src)
        wav = to_wav(src)
        text = transcribe(wav)
        post_json(f"{SPACE_URL}/api/tg_voice_result", {"chat_id": chat_id, "transcript": text, "duration_s": item.get("duration_s", 0)})
        print(f"voice {chat_id}: OK ({len(text)} chars)")
    except Exception as e:
        print(f"voice {chat_id}: FAIL {e}")
        try:
            post_json(f"{SPACE_URL}/api/tg_voice_fail", {"chat_id": chat_id, "error": str(e)})
        except Exception:
            pass


def main() -> None:
    if not BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN required")
        sys.exit(1)
    while True:
        try:
            items = get_json(f"{SPACE_URL}/api/tg_voice_pending").get("items", [])
            if items:
                print(f"[{time.strftime('%H:%M:%S')}] voice poll: {len(items)} pending")
            else:
                print(f"[{time.strftime('%H:%M:%S')}] voice poll: empty")
            for item in items:
                process(item)
        except Exception as e:
            print(f"[{time.strftime('%H:%M:%S')}] poll voice failed: {e}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
