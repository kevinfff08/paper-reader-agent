"""Runtime configuration for PaperReader."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class Settings:
    """Application settings loaded from the environment."""

    llm_provider: str = os.getenv("LLM_PROVIDER", "openai")
    llm_mode: str = os.getenv("LLM_MODE", "api-key")
    llm_model: str | None = os.getenv("LLM_MODEL") or None
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY") or None
    claude_api_key: str | None = os.getenv("CLAUDE_API_KEY") or None
    llm_proxy_url: str | None = os.getenv("LLM_PROXY_URL") or None
    semantic_scholar_api_key: str | None = os.getenv("SEMANTIC_SCHOLAR_API_KEY") or None
    openalex_email: str | None = os.getenv("OPENALEX_EMAIL") or None
    tavily_api_key: str | None = os.getenv("TAVILY_API_KEY") or None
    session_data_root: Path = Path(os.getenv("SESSION_DATA_ROOT", "data/sessions"))
    max_parse_chars: int = int(os.getenv("MAX_PARSE_CHARS", "120000"))


def get_settings() -> Settings:
    """Return current application settings."""
    return Settings()
