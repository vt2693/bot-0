import json
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)
BASE_URL = "https://connect.composio.dev/mcp"


class ComposioMCP:
    def __init__(self, api_key: str = ""):
        self.api_key = api_key or ""
        self._client: Optional[httpx.AsyncClient] = None
        self._ready = False
        self._tools: list[dict] = []
        self._request_id = 0
        self._error = ""

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def initialize_async(self) -> bool:
        if not self.api_key:
            return False
        self._client = httpx.AsyncClient(timeout=30.0)
        try:
            await self._rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "Hermes", "version": "1.0"}})
            # Try tools/list with apps filter first, fallback to unfiltered
            import os as _os
            apps_raw = _os.getenv("COMPOSIO_APPS", "")
            apps = [a.strip() for a in apps_raw.split(",") if a.strip()] if apps_raw else []
            params = {"apps": apps} if apps else {}
            tools = await self._rpc("tools/list", params) or {}
            self._tools = tools.get("tools", [])
            tool_names = [t.get("name", "?") for t in self._tools]
            logger.info("Composio tools (apps=%s): %s", apps or "all", tool_names)
            self._ready = True
            return True
        except Exception as e:
            self._error = str(e)
            logger.exception("Composio init failed")
            return False

    async def _rpc(self, method: str, params: dict) -> Optional[dict]:
        if not self._client:
            return None
        self._request_id += 1
        headers = {"x-consumer-api-key": self.api_key, "Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": self._request_id}
        r = await self._client.post(BASE_URL, json=payload, headers=headers)
        r.raise_for_status()
        text = r.text.strip()
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("data: "):
                data = json.loads(line[6:])
                return data.get("result")
        return json.loads(text).get("result")

    def get_openai_tools(self) -> list[dict]:
        tools = []
        for t in self._tools[:64]:
            name = t.get("name")
            if name:
                tools.append({"type": "function", "function": {"name": name, "description": t.get("description", "Composio tool"), "parameters": t.get("inputSchema", {"type": "object", "properties": {}})}})
        return tools

    async def call_tool(self, name: str, arguments: dict) -> dict:
        return await self._rpc("tools/call", {"name": name, "arguments": arguments}) or {}

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
        self._ready = False

    def status(self) -> dict:
        return {"ready": self._ready, "configured": self.configured, "tool_count": len(self._tools), "error": self._error}
