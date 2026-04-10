from backend.app.llm.client import LLMClient, default_model, normalize_openai_base_url


def test_normalize_openai_base_url_adds_v1() -> None:
    assert normalize_openai_base_url("http://localhost:8317") == "http://localhost:8317/v1"


def test_normalize_openai_base_url_keeps_existing_v1() -> None:
    assert normalize_openai_base_url("http://localhost:8317/v1") == "http://localhost:8317/v1"


def test_default_model_is_provider_specific() -> None:
    assert default_model("openai") == "gpt-4.1-mini"
    assert default_model("claude").startswith("claude")


def test_llm_client_configuration_logic() -> None:
    assert not LLMClient(provider="openai", mode="api-key").is_configured
    assert LLMClient(provider="openai", mode="api-key", api_key="x").is_configured
    assert LLMClient(provider="openai", mode="setup-token", base_url="http://localhost:8317").is_configured
