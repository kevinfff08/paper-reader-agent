import httpx

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


def test_stream_chat_parses_openai_sse(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        content = (
            'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":" world"}}]}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(200, text=content, headers={"content-type": "text/event-stream"})

    transport = httpx.MockTransport(handler)
    original_client = httpx.Client

    def patched_client(*args, **kwargs):
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", patched_client)
    client = LLMClient(provider="openai", mode="api-key", api_key="x", base_url="http://localhost:9999")

    events = list(client.stream_chat([{"role": "user", "content": "Hi"}]))
    assert events == [
        {"type": "text_delta", "delta": "Hello"},
        {"type": "text_delta", "delta": " world"},
    ]


def test_stream_chat_falls_back_for_claude(monkeypatch) -> None:
    client = LLMClient(provider="claude", mode="api-key", api_key="x")
    monkeypatch.setattr(LLMClient, "generate", lambda *args, **kwargs: "Fallback text")

    events = list(client.stream_chat([{"role": "user", "content": "Hi"}]))
    assert events == [{"type": "text_delta", "delta": "Fallback text"}]


def test_proxy_unknown_model_error_is_not_retried(monkeypatch) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(502, json={"error": {"message": "unknown provider for model gpt-5.5"}})

    transport = httpx.MockTransport(handler)
    original_client = httpx.Client

    def patched_client(*args, **kwargs):
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", patched_client)
    client = LLMClient(provider="openai", mode="setup-token", base_url="http://localhost:8317", model="gpt-5.5")

    try:
        client.generate("Hi")
    except httpx.HTTPStatusError:
        pass

    assert calls == 1


def test_proxy_request_timeout_can_recover(monkeypatch) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(408, json={"error": {"message": "Request Timeout"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "Recovered explanation"}}]})

    original_client = httpx.Client

    def patched_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", patched_client)
    monkeypatch.setattr("backend.app.llm.client.time.sleep", lambda _: None)
    client = LLMClient(mode="setup-token", base_url="http://localhost:8317", model="gpt-5.5")
    assert client.generate("Explain") == "Recovered explanation"
    assert calls == 2
