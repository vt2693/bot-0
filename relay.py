import os
import sys
import time
import json
import argparse
import urllib.request
import urllib.error

SPACE_URL = os.getenv("SPACE_URL", "https://vt2693-bot-0.hf.space").rstrip("/")
BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN", "")
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "3"))
MAX_RETRIES = 3

TELEGRAM_METHODS = {
    "sendMessage": "/sendMessage",
    "answerCallbackQuery": "/answerCallbackQuery",
    "editMessageText": "/editMessageText",
    "setMyCommands": "/setMyCommands",
    "setChatMenuButton": "/setChatMenuButton",
    "setWebhook": "/setWebhook",
}
CONFIG_METHODS = {"setMyCommands", "setChatMenuButton", "setWebhook"}


def post_json(url: str, payload: dict, timeout: int = 20) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def send_telegram(msg: dict, retry: int = 0) -> bool:
    msg = dict(msg)
    method = msg.pop("_method", "sendMessage")
    path = TELEGRAM_METHODS.get(method, "/sendMessage")
    if method == "setWebhook":
        msg.setdefault("max_connections", 40)
    if method == "sendMessage":
        msg["text"] = (msg.get("text") or "")[:4096]
    try:
        data = post_json(f"https://api.telegram.org/bot{BOT_TOKEN}{path}", msg)
        if not data.get("ok"):
            print(f"{method} failed: {data}")
        return bool(data.get("ok"))
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        if e.code == 429 and retry < MAX_RETRIES:
            try:
                wait = json.loads(body).get("parameters", {}).get("retry_after", 5)
            except Exception:
                wait = 5
            time.sleep(wait + 1)
            return send_telegram(msg, retry + 1)
        print(f"{method} HTTP {e.code}: {body[:500]}")
        return False
    except Exception as e:
        print(f"{method} failed: {e}")
        return False


def poll_outbox() -> list[dict]:
    try:
        with urllib.request.urlopen(f"{SPACE_URL}/api/tg_outbox", timeout=30) as resp:
            return json.loads(resp.read().decode()).get("messages", [])
    except Exception as e:
        print(f"poll failed: {e}")
        return []


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if not BOT_TOKEN:
        print("BOT_TOKEN or TELEGRAM_BOT_TOKEN required")
        sys.exit(1)
    while True:
        for msg in poll_outbox():
            method = msg.get("_method", "sendMessage")
            ok = send_telegram(msg)
            target = msg.get("chat_id") or method
            print(f"[{time.strftime('%H:%M:%S')}] {method} {target}: {'OK' if ok else 'FAIL'}")
        if args.once:
            break
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
