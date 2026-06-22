import json
import re
import time
import logging
from typing import Optional

from config import Settings

logger = logging.getLogger(__name__)


class HermesBridge:
    def __init__(self, settings: Settings, composio=None, browser=None):
        self.settings = settings
        self._composio = composio
        self._browser = browser
        self._ready = False
        self._error = ""
        self._provider = settings.provider_name or "none"
        self._model = self._resolve_model()
        self.memory_store = None
        self.memory_enabled = settings.MEMORY_ENABLED
        self._memory_stats = {"injections": 0, "hits": 0, "misses": 0, "extractions": 0}

    def _resolve_model(self) -> str:
        s = self.settings
        return {
            "opencode_zen": s.OPENCODE_ZEN_MODEL,
            "openrouter": s.OPENROUTER_MODEL,
            "google": s.GOOGLE_MODEL,
            "nvidia": s.NVIDIA_MODEL,
            "groq": s.GROQ_MODEL,
            "openai": s.OPENAI_MODEL,
            "anthropic": s.ANTHROPIC_MODEL,
            "huggingface": s.HF_MODEL,
        }.get(self._provider, "unknown")

    def _resolve_base_url(self) -> Optional[str]:
        s = self.settings
        return {"opencode_zen": s.OPENCODE_ZEN_BASE_URL, "openrouter": s.OPENROUTER_BASE_URL, "google": s.GOOGLE_BASE_URL, "nvidia": s.NVIDIA_BASE_URL, "groq": s.GROQ_BASE_URL, "openai": s.OPENAI_BASE_URL, "huggingface": s.HF_BASE_URL, "anthropic": None}.get(self._provider)

    def _resolve_api_key(self) -> Optional[str]:
        s = self.settings
        return {"opencode_zen": s.OPENCODE_ZEN_API_KEY, "openrouter": s.OPENROUTER_API_KEY, "google": s.GOOGLE_API_KEY, "nvidia": s.NVIDIA_API_KEY, "groq": s.GROQ_API_KEY, "openai": s.OPENAI_API_KEY, "anthropic": s.ANTHROPIC_API_KEY, "huggingface": s.HF_TOKEN}.get(self._provider)

    @property
    def memory_stats(self) -> dict:
        return dict(self._memory_stats)

    def initialize(self) -> None:
        if self._provider == "none":
            self._error = "No LLM provider configured"
            return
        self._ready = True

    def available_providers(self) -> dict:
        s = self.settings
        pairs = [("opencode_zen", s.OPENCODE_ZEN_API_KEY, s.OPENCODE_ZEN_MODEL), ("openrouter", s.OPENROUTER_API_KEY, s.OPENROUTER_MODEL), ("google", s.GOOGLE_API_KEY, s.GOOGLE_MODEL), ("nvidia", s.NVIDIA_API_KEY, s.NVIDIA_MODEL), ("groq", s.GROQ_API_KEY, s.GROQ_MODEL), ("openai", s.OPENAI_API_KEY, s.OPENAI_MODEL), ("anthropic", s.ANTHROPIC_API_KEY, s.ANTHROPIC_MODEL)]
        return {k: f"{k} ({m})" for k, key, m in pairs if key}

    def switch_provider(self, name: str) -> dict:
        if name not in self.available_providers():
            return {"success": False, "error": f"Unknown provider: {name}"}
        self._provider = name
        self._model = self._resolve_model()
        self._ready = True
        return {"success": True, "provider": self._provider, "model": self._model}

    def _build_messages(self, message: str, history: list, memory_context: str | None = None) -> list[dict]:
        sys = self.settings.SYSTEM_PROMPT
        if memory_context:
            sys += "\n\nFacts I know about the user (use these to answer accurately):\n" + memory_context
        msgs = [{"role": "system", "content": sys}]
        for item in history[-20:]:
            if isinstance(item, dict):
                role = item.get("role") or "user"
                content = item.get("content") or ""
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                msgs.append({"role": "user", "content": str(item[0])})
                msgs.append({"role": "assistant", "content": str(item[1])})
                continue
            else:
                role = "user" if len(msgs) % 2 else "assistant"
                content = str(item)
            if content:
                msgs.append({"role": role, "content": content})
        msgs.append({"role": "user", "content": message})
        return msgs

    def _get_tools(self) -> list[dict]:
        tools = []
        if self._composio and self._composio.status().get("ready"):
            tools.extend(self._composio.get_openai_tools())
        if self._browser and self._browser.ready:
            tools.extend(self._browser.get_openai_tools())
        return tools

    def chat(self, message: str, history: list | None = None, memory_context: str | None = None) -> str:
        if not self._ready:
            return "Hermes Agent is not configured. Add a provider API key."
        try:
            return self._call_llm(message, history or [], memory_context)
        except Exception as e:
            logger.exception("Chat failed")
            return f"Error: {e}"

    def _call_llm(self, message: str, history: list, memory_context: str | None = None) -> str:
        import openai
        client = openai.OpenAI(api_key=self._resolve_api_key(), base_url=self._resolve_base_url(), max_retries=0)
        messages = self._build_messages(message, history, memory_context)
        tools = self._get_tools()
        kwargs = {"model": self._model, "messages": messages, "max_tokens": self.settings.MAX_TOKENS, "temperature": self.settings.TEMPERATURE}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        for _ in range(4):
            resp = client.chat.completions.create(**kwargs)
            msg = resp.choices[0].message
            calls = getattr(msg, "tool_calls", None) or []
            if not calls:
                return msg.content or ""
            messages.append({"role": "assistant", "content": msg.content or "", "tool_calls": [c.model_dump() for c in calls]})
            for c in calls:
                name = c.function.name
                args = json.loads(c.function.arguments or "{}")
                result = self._execute_tool(name, args)
                messages.append({"role": "tool", "tool_call_id": c.id, "content": result[:12000]})
            kwargs["messages"] = messages
        return "Tool loop stopped after 4 rounds."

    def _execute_tool(self, name: str, args: dict) -> str:
        import asyncio
        try:
            if self._browser and name == "browse_web":
                loop = asyncio.new_event_loop()
                try:
                    return loop.run_until_complete(self._browser.execute_tool(name, args))
                finally:
                    loop.close()
            if self._composio:
                loop = asyncio.new_event_loop()
                try:
                    return json.dumps(loop.run_until_complete(self._composio.call_tool(name, args)), default=str)
                finally:
                    loop.close()
        except Exception as e:
            return f"Tool {name} failed: {e}"
        return f"Unknown tool: {name}"

    def _extract_facts(self, message: str, scope: str) -> None:
        if not self.memory_store or not self.settings.MEMORY_AUTO_EXTRACT:
            return
        patterns = [r"(?:remember|save|store|note)\s+that\s+(.+?)(?:\.|$)", r"\bmy name is\s+(.+?)(?:\.|$)", r"\bi like\s+(.+?)(?:\.|$)", r"\bi work (?:at|for|as)\s+(.+?)(?:\.|$)"]
        for pat in patterns:
            for m in re.findall(pat, message, re.I):
                fact = m.strip()
                if len(fact) > 2:
                    if not re.search(r"^(user|my|i )", fact, re.I):
                        fact = "User: " + fact
                    existing = [x for x in self.memory_store.search(fact, scope, 3) if x["content"].strip().lower() == fact.lower()]
                    if not existing:
                        self.memory_store.add(fact, scope)
                        self._memory_stats["extractions"] += 1

    def chat_with_memory(self, message: str, history: list | None = None, scope: str = "global") -> str:
        mem_block = None
        if self.memory_enabled and self.memory_store:
            self._memory_stats["injections"] += 1
            mems = self.memory_store.get_relevant(message, scope, 5)
            if mems:
                self._memory_stats["hits"] += 1
                mem_block = "\n".join("- " + m["content"] for m in mems)
            else:
                self._memory_stats["misses"] += 1
        response = self.chat(message, history or [], mem_block)
        self._extract_facts(message, scope)
        return response

    def generate_minutes(self, transcript: str) -> str:
        prompt = "Summarize this voice memo into concise meeting minutes with key points, decisions, action items, and next steps.\n\nTranscript:\n" + transcript[:12000]
        return self.chat(prompt, [])

    def status(self) -> dict:
        return {"ready": self._ready, "error": self._error, "provider": self._provider, "model": self._model, "memory": self.memory_stats, "browser": self._browser.status() if self._browser else {}, "providers": self.available_providers()}
