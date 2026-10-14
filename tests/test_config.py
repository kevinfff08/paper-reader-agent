from __future__ import annotations

from backend.app.core.config import Settings


def test_settings_strips_pasted_model_quotes(monkeypatch) -> None:
    monkeypatch.setenv("LLM_MODEL", "\u201cgpt-5.4\u201d")

    assert Settings().llm_model == "gpt-5.4"
def test_environment_and_paths_are_independent_of_working_directory(monkeypatch, tmp_path):
    from backend.app.core import config

    (tmp_path / ".env").write_text('LLM_MODEL=from-file\nLLM_MODE=setup-token\n', encoding="utf-8")
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("PAPERREADER_TEST_MODE", "0")
    monkeypatch.setenv("LLM_MODEL", "explicit-model")
    monkeypatch.delenv("LLM_MODE", raising=False)
    monkeypatch.setenv("SESSION_DATA_ROOT", "data/sessions")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    settings = config.get_settings()
    assert settings.llm_model == "explicit-model"
    assert settings.llm_mode == "setup-token"
    assert settings.session_data_root == tmp_path / "data/sessions"


