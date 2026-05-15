from __future__ import annotations

from backend.app.core.config import Settings


def test_settings_strips_pasted_model_quotes(monkeypatch) -> None:
    monkeypatch.setenv("LLM_MODEL", "\u201cgpt-5.4\u201d")

    assert Settings().llm_model == "gpt-5.4"
