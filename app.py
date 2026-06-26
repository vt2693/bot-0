import os
import sys
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import gradio as gr
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings, Settings
from healthcheck import run_healthcheck
from memory_store import MemoryStore
from composio_mcp import ComposioMCP
from browser_tool import BrowserTool
from hermes_bridge import HermesBridge
from telegram_bot import TelegramBot

logging.basicConfig(level=get_settings().LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s", handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)

_bridge = None
_store = None
_composio = None
_browser = None
_tg = None
_background_tasks: set[asyncio.Task] = set()


def _task_done(t: asyncio.Task) -> None:
    _background_tasks.discard(t)
    try:
        exc = t.exception()
        if exc:
            logger.error("Background task failed: %s", exc)
    except asyncio.CancelledError:
        pass


def _trusted(request: Request, settings: Settings) -> bool:
    if not settings.MEMORY_API_KEY and not settings.TELEGRAM_BOT_TOKEN:
        return True
    key = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    return key in (settings.MEMORY_API_KEY or "", settings.TELEGRAM_BOT_TOKEN or "")


def validate_environment(settings: Settings) -> None:
    for d in [settings.LOG_DIR, settings.DATA_DIR, settings.ASSETS_DIR, settings.HERMES_HOME, settings.TEMP_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def get_memory_store() -> MemoryStore:
    global _store
    if _store is None:
        s = get_settings()
        _store = MemoryStore(s.MEMORY_DB_PATH or str(s.DATA_DIR / "memory.db"))
    return _store


def get_composio() -> ComposioMCP:
    global _composio
    if _composio is None:
        _composio = ComposioMCP(get_settings().COMPOSIO_CONSUMER_API_KEY or "")
    return _composio


def get_browser() -> BrowserTool:
    global _browser
    if _browser is None:
        _browser = BrowserTool(get_settings())
    return _browser


def get_bridge() -> HermesBridge:
    global _bridge
    if _bridge is None:
        _bridge = HermesBridge(get_settings(), composio=get_composio(), browser=get_browser())
        _bridge.memory_store = get_memory_store()
    return _bridge


def get_telegram_bot() -> TelegramBot:
    global _tg
    if _tg is None:
        s = get_settings()
        _tg = TelegramBot(s.TELEGRAM_BOT_TOKEN or "", lambda msg, hist, scope="global": get_bridge().chat_with_memory(msg, hist, scope), bridge=get_bridge(), allowed_users=s.TELEGRAM_ALLOWED_USERS)
    return _tg


def build_gradio_app(settings: Settings) -> gr.Blocks:
    with gr.Blocks(title=settings.APP_NAME, theme=gr.themes.Soft(), analytics_enabled=False) as demo:
        gr.Markdown(f"# {settings.APP_NAME}\nDocker Space: Hermes Agent + Telegram relay + memory + tools")
        provider = gr.Dropdown(label="Provider", choices=list(get_bridge().available_providers().keys()), value=get_bridge().status().get("provider"))
        model = gr.Textbox(label="Model", value=get_bridge().status().get("model"), interactive=False)
        chatbot = gr.Chatbot(type="messages", height=520)
        msg = gr.Textbox(label="Message", placeholder="Ask Hermes…")
        clear = gr.Button("Clear")

        def send(text, hist):
            if not text:
                return hist, ""
            reply = get_bridge().chat_with_memory(text, hist or [], "gradio")
            hist = (hist or []) + [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
            return hist, ""

        def switch(p):
            r = get_bridge().switch_provider(p)
            return r.get("model", get_bridge().status().get("model"))

        msg.submit(send, [msg, chatbot], [chatbot, msg])
        clear.click(lambda: [], None, chatbot)
        provider.change(switch, provider, model)
    return demo


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    s = get_settings()
    validate_environment(s)
    bridge = get_bridge()
    if s.provider_name:
        bridge.initialize()
    if get_composio().configured:
        t = asyncio.create_task(get_composio().initialize_async())
        t.add_done_callback(_task_done); _background_tasks.add(t)
    t = asyncio.create_task(get_browser().initialize_async())
    t.add_done_callback(_task_done); _background_tasks.add(t)
    tg = get_telegram_bot()
    if tg.configured:
        await tg.initialize_async()
        t = asyncio.create_task(tg.process_queue_worker())
        t.add_done_callback(_task_done); _background_tasks.add(t)

    # Periodic memory backup to HF Hub (survives restarts)
    async def _periodic_memory_backup():
        while True:
            await asyncio.sleep(120)
            try:
                store = get_memory_store()
                if store.status()["fact_count"] > 0:
                    store.sync()
            except Exception as e:
                logger.error("Memory backup periodic: %s", e)
    bt = asyncio.create_task(_periodic_memory_backup())
    bt.add_done_callback(_task_done); _background_tasks.add(bt)
    yield
    await get_composio().close()
    await tg.stop()
    store = get_memory_store()
    if store.status()["fact_count"] > 0:
        store.sync()
    store.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION, lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    @app.get("/health")
    async def health():
        r = run_healthcheck()
        r["hermes"] = get_bridge().status()
        r["telegram"] = get_telegram_bot().status()
        r["memory"] = get_memory_store().status()
        r["composio"] = get_composio().status()
        r["browser"] = get_browser().status()
        r["_debug"] = {"HF_TOKEN": "SET" if os.getenv("HF_TOKEN") else "NOT_SET", "MEMORY_SPACE_ID": os.getenv("MEMORY_SPACE_ID", "not_set"), "SPACE_ID": os.getenv("SPACE_ID", "not_set")}
        return r

    @app.post("/webhook/telegram")
    async def telegram_webhook(request: Request):
        tg = get_telegram_bot()
        if not tg.configured:
            return JSONResponse({"ok": False, "error": "telegram not configured"})
        try:
            import json
            raw = (await request.body()).decode("utf-8")
            tg.enqueue_update(json.loads(raw))
            return JSONResponse({"ok": True})
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    @app.get("/api/tg_outbox")
    async def tg_outbox():
        return {"messages": await get_telegram_bot().drain_outbox()}

    @app.get("/api/tg_peek")
    async def tg_peek():
        return {"messages": await get_telegram_bot().peek_outbox()}

    @app.post("/api/tg_reconfigure")
    async def tg_reconfigure():
        tg = get_telegram_bot()
        tg.configure_commands()
        tg.enqueue_config("setWebhook", {"url": os.getenv("TELEGRAM_WEBHOOK_URL", settings.SPACE_URL + "/webhook/telegram"), "allowed_updates": ["message", "edited_message", "callback_query"]})
        return {"ok": True}

    @app.get("/api/tg_voice_pending")
    async def tg_voice_pending():
        return {"items": get_telegram_bot().drain_voice_queue()}

    @app.post("/api/tg_voice_result")
    async def tg_voice_result(request: Request):
        body = await request.json()
        minutes = get_bridge().generate_minutes(body.get("transcript", ""))
        get_telegram_bot()._send_message(int(body["chat_id"]), f"Voice Minutes ({body.get('duration_s', 0)}s)\n\n{minutes}")
        return {"ok": True, "minutes_len": len(minutes)}

    @app.post("/api/tg_voice_fail")
    async def tg_voice_fail(request: Request):
        body = await request.json()
        get_telegram_bot()._send_message(int(body["chat_id"]), "Voice processing failed: " + str(body.get("error", "unknown"))[:500])
        return {"ok": True}

    @app.api_route("/api/memory/{action:path}", methods=["GET", "POST"])
    async def memory_api(action: str, request: Request):
        if not _trusted(request, settings):
            return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
        store = get_memory_store()
        body = {}
        if request.method == "POST":
            try:
                body = await request.json()
            except Exception:
                body = {}
        if action == "add":
            return {"ok": True, "id": store.add(body.get("content", ""), body.get("scope", "global"), body.get("metadata", {}))}
        if action == "search":
            return {"ok": True, "results": store.search(body.get("query", ""), body.get("scope", "global"), body.get("limit", 5))}
        if action == "probe":
            return {"ok": True, "result": store.probe(body.get("entity", ""), body.get("scope", "global"))}
        if action == "reason":
            return {"ok": True, "result": store.reason(body.get("query", ""), body.get("scope", "global"), body.get("limit", 5))}
        if action == "feedback":
            return {"ok": store.add_feedback(body.get("content", ""), body.get("feedback", ""), body.get("scope", "global"))}
        if action == "clear":
            scope = request.query_params.get("scope", "global")
            store.clear(None if scope in ("", "all", "*") else scope)
            return {"ok": True}
        if action == "status":
            return {"ok": True, "stats": store.status(), "bridge": get_bridge().memory_stats}
        return JSONResponse({"ok": False, "error": "unknown action"}, status_code=404)

    gradio_app = build_gradio_app(settings)
    return gr.mount_gradio_app(app, gradio_app, path="/")
