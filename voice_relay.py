import os
import sys
import time
import json
import tempfile
from pathlib import Path

from tg_voice import to_wav as _to_wav
from tg_voice import tg_file_path as _tg_file_path
from tg_voice import download_file as _download_file
from tg_voice import transcribe as _transcribe

print = lambda *a, **kw: __builtins__.print(*a, **kw, flush=True)  # noqa

SPACE_URL = os.getenv("SPACE_URL", "https://vt2693-bot-0.hf.space").rstrip("/")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN", "")
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "1"))
WORK_DIR = Path(os.getenv("WORK_DIR", tempfile.gettempdir()))
WORK_DIR.mkdir(parents=True, exist_ok=True)


def get_json(url: str) -> dict:
    """GET with retries for transient failures (ECONNRESET, 503, etc.)."""
    for attempt in range(6):
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            if attempt < 5:
                wait = (2 ** attempt) * 3
                print(f"[{time.strftime('%H:%M:%S')}] get_json failed (attempt {attempt+1}): {e}, retry in {wait}s...")
                time.sleep(wait)
                continue
            raise


def post_json(url: str, payload: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


# Wrappers that inject module-level globals into tg_voice.py functions
def tg_file_path(file_id: str) -> str:
    return _tg_file_path(BOT_TOKEN, file_id)


def download_file(file_path: str, out: Path) -> None:
    _download_file(BOT_TOKEN, file_path, out)


def to_wav(src: Path) -> Path:
    return _to_wav(src)


def transcribe(wav: Path) -> str:
    return _transcribe(wav)


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
