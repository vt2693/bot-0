import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)
MAX_PAGE_LENGTH = 8000


class BrowserTool:
    def __init__(self, settings):
        self.settings = settings
        self._ready = False
        self._error = ""

    @property
    def ready(self) -> bool:
        return self._ready

    async def initialize_async(self) -> bool:
        try:
            import importlib.metadata
            importlib.metadata.version("browser-use")
            self._ready = True
            return True
        except Exception as e:
            self._error = str(e)
            return False

    def get_openai_tools(self) -> list[dict]:
        if not self._ready:
            return []
        return [
            {
                "type": "function",
                "function": {
                    "name": "browse_web",
                    "description": "Navigate to a URL and perform a web task.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "task": {"type": "string", "description": "What to do on the page"},
                            "url": {"type": "string", "description": "Optional starting URL"},
                        },
                        "required": ["task"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "extract_page_content",
                    "description": "Extract visible text from the current web page.",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                    },
                },
            },
        ]

    def _make_llm(self):
        from langchain_openai import ChatOpenAI
        p = self.settings.provider_name
        cfg = {
            "opencode_zen": (self.settings.OPENCODE_ZEN_MODEL, self.settings.OPENCODE_ZEN_API_KEY, self.settings.OPENCODE_ZEN_BASE_URL),
            "openrouter": (self.settings.OPENROUTER_MODEL, self.settings.OPENROUTER_API_KEY, self.settings.OPENROUTER_BASE_URL),
            "groq": (self.settings.GROQ_MODEL, self.settings.GROQ_API_KEY, self.settings.GROQ_BASE_URL),
            "nvidia": (self.settings.NVIDIA_MODEL, self.settings.NVIDIA_API_KEY, self.settings.NVIDIA_BASE_URL),
            "openai": (self.settings.OPENAI_MODEL, self.settings.OPENAI_API_KEY, self.settings.OPENAI_BASE_URL),
            "google": (self.settings.GOOGLE_MODEL, self.settings.GOOGLE_API_KEY, self.settings.GOOGLE_BASE_URL),
            "router_0": (self.settings.ROUTER_0_MODEL, self.settings.ROUTER_0_API_KEY, self.settings.ROUTER_0_BASE_URL),
        }.get(p)
        if not cfg:
            raise RuntimeError(f"Browser LLM unsupported for {p}")
        model, key, base_url = cfg
        return ChatOpenAI(model=model, api_key=key, base_url=base_url, temperature=0.2)

    async def execute_tool(self, name: str, args: dict) -> str:
        if name == "browse_web":
            return await self._browse_web(args.get("task", ""), args.get("url"))
        if name == "extract_page_content":
            return "No active page — use browse_web first to navigate to a URL."
        return f"Unknown browser tool: {name}"

    async def _browse_web(self, task: str, url: Optional[str] = None) -> str:
        try:
            return await asyncio.wait_for(self._run_browser(task, url), timeout=120)
        except asyncio.TimeoutError:
            return "Error: browser task timed out after 120 seconds"
        except Exception as e:
            return f"Error: browser task failed: {e}"

    async def _run_browser(self, task: str, url: Optional[str]) -> str:
        from browser_use import Agent
        from browser_use.browser.browser import Browser, BrowserConfig
        browser = Browser(config=BrowserConfig(headless=True, disable_security=True))
        try:
            full_task = f"Go to {url} and {task}" if url else task
            agent = Agent(task=full_task, llm=self._make_llm(), browser=browser, use_vision=False)
            history = await agent.run(max_steps=15)
            result = history.final_result() or ""
            return result[:MAX_PAGE_LENGTH] + ("\n[truncated]" if len(result) > MAX_PAGE_LENGTH else "")
        finally:
            await browser.close()

    def status(self) -> dict:
        return {"ready": self._ready, "error": self._error}
