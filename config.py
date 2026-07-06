import os
import logging
from pathlib import Path
from functools import lru_cache
from typing import Optional

logger = logging.getLogger(__name__)


class Settings:
    APP_NAME = os.getenv("APP_NAME", "Hermes Agent")
    APP_VERSION = os.getenv("APP_VERSION", "1.0.0")
    DEBUG = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes")
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "7860"))
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    SPACE_URL = os.getenv("SPACE_URL", "https://vt2693-bot-0.hf.space")
    MEMORY_SPACE_ID = os.getenv("MEMORY_SPACE_ID", "")

    TELEGRAM_BOT_TOKEN: Optional[str] = os.getenv("TELEGRAM_BOT_TOKEN")
    TELEGRAM_ALLOWED_USERS = os.getenv("TELEGRAM_ALLOWED_USERS", "")

    OPENROUTER_API_KEY: Optional[str] = os.getenv("OPENROUTER_API_KEY")
    GROQ_API_KEY: Optional[str] = os.getenv("GROQ_API_KEY")
    GOOGLE_API_KEY: Optional[str] = os.getenv("GOOGLE_API_KEY")
    NVIDIA_API_KEY: Optional[str] = os.getenv("NVIDIA_API_KEY")
    OPENCODE_ZEN_API_KEY: Optional[str] = os.getenv("OPENCODE_ZEN_API_KEY")
    OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY")
    ANTHROPIC_API_KEY: Optional[str] = os.getenv("ANTHROPIC_API_KEY")
    HF_TOKEN: Optional[str] = os.getenv("HF_TOKEN")
    ROUTER_0_API_KEY: Optional[str] = os.getenv("ROUTER_0_API_KEY")

    OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/free")
    OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    GOOGLE_MODEL = os.getenv("GOOGLE_MODEL", "gemini-3.1-flash-lite")
    GOOGLE_BASE_URL = os.getenv("GOOGLE_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
    NVIDIA_MODEL = os.getenv("NVIDIA_MODEL", "nvidia/nemotron-mini-4b-instruct")
    NVIDIA_BASE_URL = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
    OPENCODE_ZEN_MODEL = os.getenv("OPENCODE_ZEN_MODEL", "deepseek-v4-flash-free")
    OPENCODE_ZEN_BASE_URL = os.getenv("OPENCODE_ZEN_BASE_URL", "https://opencode.ai/zen/v1")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
    ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
    HF_MODEL = os.getenv("HF_MODEL", "NousResearch/Hermes-3-Llama-3.1-8B")
    HF_BASE_URL = os.getenv("HF_BASE_URL", "https://api-inference.huggingface.co")
    ROUTER_0_MODEL = os.getenv("ROUTER_0_MODEL", "oc/deepseek-v4-flash-free")
    ROUTER_0_BASE_URL = os.getenv("ROUTER_0_BASE_URL", "https://vt2693-router-0.hf.space/v1")

    COMPOSIO_CONSUMER_API_KEY: Optional[str] = os.getenv("COMPOSIO_CONSUMER_API_KEY")
    COMPOSIO_APPS = os.getenv("COMPOSIO_APPS", "")

    SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT", "You are Hermes Agent, a concise helpful assistant powered by Nous Research.")
    MAX_TOKENS = int(os.getenv("MAX_TOKENS", "2048"))
    TEMPERATURE = float(os.getenv("TEMPERATURE", "0.7"))
    TOOL_LOOP_MAX_ROUNDS = int(os.getenv("TOOL_LOOP_MAX_ROUNDS", "1000"))
    LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "120"))

    APP_DIR = Path("/app")
    LOG_DIR = APP_DIR / "logs"
    DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
    ASSETS_DIR = APP_DIR / "assets"
    HERMES_HOME = Path(os.getenv("HERMES_HOME", "/app/.hermes"))
    TEMP_DIR = Path(os.getenv("TEMP_DIR", "/tmp/app"))
    MEMORY_ENABLED = os.getenv("MEMORY_ENABLED", "true").lower() in ("true", "1", "yes")
    MEMORY_AUTO_EXTRACT = os.getenv("MEMORY_AUTO_EXTRACT", "true").lower() in ("true", "1", "yes")
    MEMORY_RESTORE_ON_STARTUP = os.getenv("MEMORY_RESTORE_ON_STARTUP", "false").lower() in ("true", "1", "yes")
    AUTO_LEARN = os.getenv("AUTO_LEARN", "true").lower() in ("true", "1", "yes")
    MEMORY_API_KEY: Optional[str] = os.getenv("MEMORY_API_KEY")
    MEMORY_DB_PATH = os.getenv("MEMORY_DB_PATH", "")
    BROADCAST_CHAT_ID = os.getenv("BROADCAST_CHAT_ID", "")

    @property
    def provider_name(self) -> Optional[str]:
        override = os.getenv("PROVIDER", "").strip().lower()
        valid = ("opencode_zen", "openrouter", "google", "nvidia", "groq", "openai", "anthropic", "huggingface", "router_0")
        if override in valid:
            return override
        if override:
            logger.warning("Unknown PROVIDER=%s, auto-detecting", override)
        if self.ROUTER_0_API_KEY or self.ROUTER_0_BASE_URL:
            return "router_0"
        if self.OPENCODE_ZEN_API_KEY:
            return "opencode_zen"
        if self.OPENROUTER_API_KEY:
            return "openrouter"
        if self.GOOGLE_API_KEY:
            return "google"
        if self.NVIDIA_API_KEY:
            return "nvidia"
        if self.GROQ_API_KEY:
            return "groq"
        if self.OPENAI_API_KEY:
            return "openai"
        if self.ANTHROPIC_API_KEY:
            return "anthropic"
        if self.HF_TOKEN:
            return "huggingface"
        return None

    @property
    def has_api_key(self) -> bool:
        return self.provider_name is not None


@lru_cache()
def get_settings() -> Settings:
    return Settings()
