import os
import sys
import time
import json
import argparse
import urllib.request
import urllib.error

print = lambda *a, **kw: __builtins__.print(*a, **kw, flush=True)  # noqa

SPACE_URL = os.getenv("SPACE_URL", "https://vt2693-bot-0.hf.space").rstrip("/")
BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN", "")
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "1"))
MAX_RETRIES = 3
POLL_TIMEOUT = int(os.getenv("POLL_TIMEOUT", "25"))  # must cover cold-boot delay
POLLING_MODE = os.getenv("POLLING_MODE", "true").lower() in ("true", "1", "yes")

TELEGRAM_METHODS = {
    "sendMessage": "/sendMessage",
    "sendChatAction": "/sendChatAction",
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


# -- Inbound: getUpdates long-polling ----------------------------------------
# Avoids cold-boot issue: Telegram holds the update queue (up to 24h).
# We poll with a 30s long-poll timeout; even if Space cold-boots, the update
# stays in Telegram's queue and arrives on the next poll cycle.

_telegram_offset = 0


def delete_webhook() -> bool:
    """Remove webhook so Telegram queues updates for getUpdates instead."""
    try:
        data = post_json(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook", {"drop_pending_updates": True}, timeout=10)
        ok = data.get("ok", False)
        print(f"deleteWebhook: {'OK' if ok else 'FAIL'} {data}")
        return ok
    except Exception as e:
        print(f"deleteWebhook failed: {e}")
        return False


def get_updates() -> list[dict]:
    """Long-poll Telegram for incoming updates. Returns raw update dicts."""
    global _telegram_offset
    params = {"offset": _telegram_offset, "timeout": 30, "allowed_updates": ["message", "edited_message", "callback_query"]}
    try:
        data = post_json(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates", params, timeout=35)
        results = data.get("result", [])
        if results:
            _telegram_offset = results[-1]["update_id"] + 1
            print(f"getUpdates: {len(results)} update(s)")
        return results
    except Exception as e:
        return []


def forward_to_space(update: dict) -> bool:
    """POST a single update to the Space webhook endpoint. Cold-boot tolerant."""
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                f"{SPACE_URL}/webhook/telegram",
                data=json.dumps(update).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=POLL_TIMEOUT) as resp:
                return True
        except Exception as e:
            wait = (2 ** attempt) * 3
            print(f"forward attempt {attempt+1} failed: {e}, retry in {wait}s...")
            if attempt < 2:
                time.sleep(wait)
                continue
            return False


# -- Outbound: poll Space outbox ---------------------------------------------

def poll_outbox() -> list[dict]:
    """Poll with backoff for transient errors (cold-boot 503, ECONNRESET, etc.).

    Server cold-boots after ~15 min idle and takes 15-60s.
    Nginx reverse proxy may reset connections under load. Retry with backoff.
    """
    for attempt in range(6):
        try:
            with urllib.request.urlopen(f"{SPACE_URL}/api/tg_outbox", timeout=POLL_TIMEOUT) as resp:
                return json.loads(resp.read().decode()).get("messages", [])
        except Exception as e:
            wait = (2 ** attempt) * 3
            print(f"outbox poll failed (attempt {attempt+1}): {e}, retry in {wait}s...")
            if attempt < 5:
                time.sleep(wait)
                continue
            print(f"outbox poll gave up after 6 attempts")
            return []
    return []


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if not BOT_TOKEN:
        print("BOT_TOKEN or TELEGRAM_BOT_TOKEN required")
        sys.exit(1)

    # Phase 1: Drop webhook if polling mode, so Telegram queues updates.
    _last_webhook_delete = 0
    if POLLING_MODE:
        delete_webhook()
        _last_webhook_delete = time.time()

    while True:
        # Inbound: poll Telegram for new updates (getUpdates long-poll)
        updates = []
        if POLLING_MODE:
            # Re-delete webhook every ~60s to fight Space restart re-enqueues
            if time.time() - _last_webhook_delete > 60:
                delete_webhook()
                _last_webhook_delete = time.time()
            updates = get_updates()
            for update in updates:
                ok = forward_to_space(update)
                print(f"[{time.strftime('%H:%M:%S')}] forward update_id {update.get('update_id','?')}: {'OK' if ok else 'FAIL'}")

        # Outbound: drain Space outbox (skip setWebhook when polling — it
        # would override polling mode and re-enable direct webhook delivery)
        msgs = poll_outbox()
        for msg in msgs:
            method = msg.get("_method", "sendMessage")
            if POLLING_MODE and method == "setWebhook":
                continue
            ok = send_telegram(msg)
            target = msg.get("chat_id") or method
            print(f"[{time.strftime('%H:%M:%S')}] {method} {target}: {'OK' if ok else 'FAIL'}")
        if not msgs and not updates:
            print(f"[{time.strftime('%H:%M:%S')}] poll: empty")
        if args.once:
            break
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
