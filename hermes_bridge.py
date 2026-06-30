import json
import re
import time
import logging
from typing import Optional

from config import Settings

logger = logging.getLogger(__name__)


class HermesBridge:
    def __init__(self, settings: Settings, composio=None):
        self.settings = settings
        self._composio = composio
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
            "router_0": s.ROUTER_0_MODEL,
        }.get(self._provider, "unknown")

    def _resolve_base_url(self) -> Optional[str]:
        s = self.settings
        return {"opencode_zen": s.OPENCODE_ZEN_BASE_URL, "openrouter": s.OPENROUTER_BASE_URL, "google": s.GOOGLE_BASE_URL, "nvidia": s.NVIDIA_BASE_URL, "groq": s.GROQ_BASE_URL, "openai": s.OPENAI_BASE_URL, "huggingface": s.HF_BASE_URL, "anthropic": None, "router_0": s.ROUTER_0_BASE_URL}.get(self._provider)

    def _resolve_api_key(self) -> Optional[str]:
        s = self.settings
        return {"opencode_zen": s.OPENCODE_ZEN_API_KEY, "openrouter": s.OPENROUTER_API_KEY, "google": s.GOOGLE_API_KEY, "nvidia": s.NVIDIA_API_KEY, "groq": s.GROQ_API_KEY, "openai": s.OPENAI_API_KEY, "anthropic": s.ANTHROPIC_API_KEY, "huggingface": s.HF_TOKEN, "router_0": s.ROUTER_0_API_KEY}.get(self._provider)

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
        pairs = [("opencode_zen", s.OPENCODE_ZEN_API_KEY, s.OPENCODE_ZEN_MODEL), ("openrouter", s.OPENROUTER_API_KEY, s.OPENROUTER_MODEL), ("google", s.GOOGLE_API_KEY, s.GOOGLE_MODEL), ("nvidia", s.NVIDIA_API_KEY, s.NVIDIA_MODEL), ("groq", s.GROQ_API_KEY, s.GROQ_MODEL), ("openai", s.OPENAI_API_KEY, s.OPENAI_MODEL), ("anthropic", s.ANTHROPIC_API_KEY, s.ANTHROPIC_MODEL), ("router_0", s.ROUTER_0_API_KEY, s.ROUTER_0_MODEL)]
        return {k: f"{k} ({m})" for k, key, m in pairs if key}

    def switch_model(self, model: str) -> dict:
        if not model:
            return {"success": False, "error": "Model name empty"}
        self._model = model
        return {"success": True, "provider": self._provider, "model": self._model}

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
        for item in history[-100:]:
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
        if self._composio and self._composio.status().get("ready"):
            return self._composio.get_openai_tools()
        return []

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
        for _ in range(25):
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
        return f"Tool loop stopped after 25 rounds. The task may need more steps or the tools are failing. Try a simpler request."

    def _execute_tool(self, name: str, args: dict) -> str:
        import asyncio
        try:
            if self._composio:
                loop = asyncio.new_event_loop()
                try:
                    return json.dumps(loop.run_until_complete(self._composio.call_tool(name, args)), default=str)
                finally:
                    loop.close()
        except Exception as e:
            return f"Tool {name} failed: {e}"
        return f"Unknown tool: {name}"

    def _extract_facts(self, message: str, response: str, scope: str) -> None:
        if not self.memory_store or not self.settings.MEMORY_AUTO_EXTRACT:
            return
        # Scan message and response separately so \n boundaries work correctly
        for text in (message, response):
            self._scan_for_facts(text, scope)

    def _scan_for_facts(self, text: str, scope: str) -> None:
        patterns = [
            r"(?:remember|save|store|note)\s+(?:that\s+)?(.+?)(?:\.|$|\n)",
            r"\bmy name(?:\s+is)?\s+(.+?)(?:\.|$|\n)",
            r"\bi (?:like|love|enjoy|hate|dislike)\s+(.+?)(?:\.|$|\n)",
            r"\bi (?:work|study)(?:\s+at|\s+for|\s+as)?\s+(.+?)(?:\.|$|\n)",
            r"\bi live\s+(?:in|at|near)\s+(.+?)(?:\.|$|\n)",
            r"\bi (?:am|was)\s+(?:a\s+|an\s+)?(.+?)(?:\.|$|\n)",
            r"\bmy (?:email|phone|address|website)\s+(?:is\s+)?(.+?)(?:\.|$|\n)",
        ]
        for pat in patterns:
            for m in re.findall(pat, text, re.I):
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
            mems = self.memory_store.get_relevant(message, scope, 100)
            if mems:
                self._memory_stats["hits"] += 1
                mem_block = "\n".join("- " + m["content"] for m in mems)
            else:
                self._memory_stats["misses"] += 1
        response = self.chat(message, history or [], mem_block)
        self._extract_facts(message, response, scope)
        return response

    def parse_schedule(self, text: str) -> dict:
        """Parse natural-language scheduling intent via constrained LLM call.

        Returns {\"interval_minutes\": int, \"prompt\": str} or {\"error\": str}.
        """
        sys_prompt = (
            "Extract scheduling intent from the user's text. "
            "Return ONLY valid JSON (no other text) with one of these shapes:\n"
            '{"interval_minutes": number, "prompt": string}\n'
            '{"error": "reason"}\n\n'
            "Examples:\n"
            '- "check gmail every 15 minutes" -> {"interval_minutes": 15, "prompt": "check my gmail"}\n'
            '- "every 2 hours, summarize news" -> {"interval_minutes": 120, "prompt": "summarize news"}\n'
            '- "hello" -> {"error": "no scheduling intent found"}\n\n'
            "Rules:\n"
            '- interval_minutes is how often to run the task, in minutes\n'
            '- prompt is the task description without timing words\n'
            '- If no recurring schedule is described, return an error'
        )
        try:
            body = self.chat(text, [], sys_prompt)
            return json.loads(body)
        except (json.JSONDecodeError, Exception) as e:
            return {"error": f"Parse failed: {e}"}

    def generate_minutes(self, transcript: str) -> str:
        prompt = "Summarize this voice memo into concise meeting minutes with key points, decisions, action items, and next steps.\n\nTranscript:\n" + transcript[:12000]
        return self.chat(prompt, [])

    def status(self) -> dict:
        return {"ready": self._ready, "error": self._error, "provider": self._provider, "model": self._model, "memory": self.memory_stats, "providers": self.available_providers()}
