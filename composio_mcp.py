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
            tools = await self._rpc("tools/list", {}) or {}
            self._tools = tools.get("tools", [])
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
                try:
                    data = json.loads(line[6:])
                    return data.get("result")
                except json.JSONDecodeError:
                    continue  # skip non-JSON lines (warnings, partial chunks)
        try:
            return json.loads(text).get("result")
        except json.JSONDecodeError:
            return {"error": f"unparseable response: {text[:200]}"}

    def get_openai_tools(self) -> list[dict]:
        tools = []
        for t in self._tools[:64]:
            name = t.get("name")
            if name:
                tools.append({"type": "function", "function": {"name": name, "description": t.get("description", "Composio tool"), "parameters": t.get("inputSchema", {"type": "object", "properties": {}})}})
        return tools

    async def call_tool(self, name: str, arguments: dict) -> dict:
        return await self._rpc("tools/call", {"name": name, "arguments": arguments}) or {}

    def call_tool_sync(self, name: str, arguments: dict) -> dict:
        """Synchronous version — uses httpx.Client, no event loop needed.

        Used from HermesBridge._execute_tool which runs in a thread pool
        (asyncio.to_thread) and cannot safely create a new event loop.
        """
        import httpx as _httpx
        with _httpx.Client(timeout=120.0) as client:
            self._request_id += 1
            headers = {"x-consumer-api-key": self.api_key, "Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
            payload = {"jsonrpc": "2.0", "method": "tools/call", "params": {"name": name, "arguments": arguments}, "id": self._request_id}
            r = client.post(BASE_URL, json=payload, headers=headers)
            r.raise_for_status()
            text = r.text.strip()
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("data: "):
                    data = json.loads(line[6:])
                    return data.get("result") or {}
            return json.loads(text).get("result") or {}

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
        self._ready = False

    def status(self) -> dict:
        return {"ready": self._ready, "configured": self.configured, "tool_count": len(self._tools), "error": self._error}
