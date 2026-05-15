"""Runtime configuration and safety guards for PaperReader."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


_QUOTE_PAIRS = {
    ("'", "'"),
    ('"', '"'),
    (chr(0x201C), chr(0x201D)),
    (chr(0x2018), chr(0x2019)),
}


def _env_str(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None:
        return default
    stripped = value.strip()
    if not stripped:
        return default
    if len(stripped) >= 2 and (stripped[0], stripped[-1]) in _QUOTE_PAIRS:
        stripped = stripped[1:-1].strip()
    return stripped or default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_path(name: str, default: str) -> Path:
    return Path(os.getenv(name, default))


def is_test_mode_enabled() -> bool:
    """Return whether the process is running in protected test mode."""
    return os.getenv("PAPERREADER_TEST_MODE", "0").strip().lower() in {"1", "true", "yes", "on"}


def _resolve_under_repo(path: Path, repo_root: Path) -> Path:
    return path.resolve() if path.is_absolute() else (repo_root / path).resolve()


def ensure_safe_session_root(root: Path, *, test_mode: bool, repo_root: Path | None = None) -> None:
    """Reject formal session storage when tests are running."""
    if not test_mode:
        return
    base = repo_root or Path.cwd()
    candidate = _resolve_under_repo(root, base)
    formal = _resolve_under_repo(Path("data/sessions"), base)
    if candidate == formal or formal in candidate.parents:
        raise ValueError(
            "PAPERREADER_TEST_MODE is enabled, but SESSION_DATA_ROOT points at formal data/sessions storage. "
            "Use an isolated root under .tmp-tests instead."
        )


@dataclass(slots=True)
class Settings:
    """Application settings loaded from the environment."""

    llm_provider: str = field(default_factory=lambda: _env_str("LLM_PROVIDER", "openai") or "openai")
    llm_mode: str = field(default_factory=lambda: _env_str("LLM_MODE", "api-key") or "api-key")
    llm_model: str | None = field(default_factory=lambda: _env_str("LLM_MODEL"))
    openai_api_key: str | None = field(default_factory=lambda: _env_str("OPENAI_API_KEY"))
    claude_api_key: str | None = field(default_factory=lambda: _env_str("CLAUDE_API_KEY"))
    llm_proxy_url: str | None = field(default_factory=lambda: _env_str("LLM_PROXY_URL"))
    semantic_scholar_api_key: str | None = field(default_factory=lambda: _env_str("SEMANTIC_SCHOLAR_API_KEY"))
    openalex_email: str | None = field(default_factory=lambda: _env_str("OPENALEX_EMAIL"))
    tavily_api_key: str | None = field(default_factory=lambda: _env_str("TAVILY_API_KEY"))
    session_data_root: Path = field(default_factory=lambda: _env_path("SESSION_DATA_ROOT", "data/sessions"))
    max_parse_chars: int = field(default_factory=lambda: _env_int("MAX_PARSE_CHARS", 120000))
    docling_enabled: bool = field(default_factory=lambda: _env_bool("DOCLING_ENABLED", True))
    docling_ocr_enabled: bool = field(default_factory=lambda: _env_bool("DOCLING_OCR_ENABLED", True))
    docling_artifacts_path: Path = field(default_factory=lambda: _env_path("DOCLING_ARTIFACTS_PATH", ".cache/docling"))
    docling_max_pages: int = field(default_factory=lambda: _env_int("DOCLING_MAX_PAGES", 80))
    docling_max_file_size_mb: int = field(default_factory=lambda: _env_int("DOCLING_MAX_FILE_SIZE_MB", 50))
    docling_omp_threads: int = field(default_factory=lambda: _env_int("DOCLING_OMP_THREADS", 4))
    docling_batch_size: int = field(default_factory=lambda: _env_int("DOCLING_BATCH_SIZE", 1))
    docling_device: str = field(default_factory=lambda: _env_str("DOCLING_DEVICE", "auto") or "auto")
    test_mode: bool = field(default_factory=is_test_mode_enabled)


def get_settings() -> Settings:
    """Return current application settings."""
    return Settings()
