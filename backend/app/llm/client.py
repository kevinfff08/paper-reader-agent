"""LLM client supporting OpenAI, Claude, and CLIProxy-style base URLs."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Iterator

import httpx

from backend.app.logging.session_logger import get_app_logger


logger = get_app_logger("llm")

_OPENAI_BASE_URL = "https://api.openai.com/v1"
_CLAUDE_BASE_URL = "https://api.anthropic.com/v1"
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504, 529}


def normalize_openai_base_url(base_url: str) -> str:
    """Normalize an OpenAI-compatible base URL to include /v1."""
    stripped = base_url.rstrip("/")
    if stripped.endswith("/v1"):
        return stripped
    return f"{stripped}/v1"


def default_model(provider: str) -> str:
    """Return a provider-specific default model."""
    return "gpt-4.1-mini" if provider == "openai" else "claude-sonnet-4-5"


@dataclass(slots=True)
class LLMClient:
    """Thin runtime client for text generation."""

    provider: str = "openai"
    mode: str = "api-key"
    api_key: str | None = None
    model: str | None = None
    base_url: str | None = None
    timeout_seconds: float = 180.0

    @property
    def resolved_model(self) -> str:
        """Return the configured or default model."""
        return self.model or default_model(self.provider)

    @property
    def is_configured(self) -> bool:
        """Return whether external text generation is configured."""
        if self.mode == "setup-token":
            return bool(self.base_url)
        return bool(self.api_key)

    def generate(
        self,
        prompt: str,
        *,
        system: str = "",
        temperature: float = 0.2,
        max_tokens: int = 2500,
    ) -> str:
        """Generate text using the configured provider."""
        if not self.is_configured:
            raise RuntimeError("LLM client is not configured")

        last_error: Exception | None = None
        for attempt in range(5):
            try:
                t0 = time.time()
                if self.provider == "claude":
                    result = self._generate_claude(
                        prompt,
                        system=system,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                else:
                    result = self._generate_openai(
                        prompt,
                        system=system,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                logger.info("LLM call completed in %.1fs", time.time() - t0)
                return result
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code not in _RETRYABLE_STATUS_CODES:
                    raise
                time.sleep(2 ** attempt)

        raise last_error or RuntimeError("Unknown LLM failure")

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str = "",
        temperature: float = 0.2,
        max_tokens: int = 2500,
    ) -> Iterator[dict[str, Any]]:
        """Yield normalized streaming chat events from an OpenAI-compatible API."""
        if not self.is_configured:
            raise RuntimeError("LLM client is not configured")

        if self.provider == "claude":
            text = self.generate(
                self._messages_to_prompt(messages),
                system=system,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            if text:
                yield {"type": "text_delta", "delta": text}
            return

        base_url = normalize_openai_base_url(self.base_url or _OPENAI_BASE_URL)
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload_messages: list[dict[str, Any]] = []
        if system:
            payload_messages.append({"role": "system", "content": system})
        payload_messages.extend(messages)

        with httpx.Client(timeout=self.timeout_seconds, headers=headers, base_url=base_url.rstrip("/") + "/") as client:
            with client.stream(
                "POST",
                "chat/completions",
                json={
                    "model": self.resolved_model,
                    "messages": payload_messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": True,
                },
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    event = self._parse_stream_line(line)
                    if event is not None:
                        yield event

    def _generate_openai(
        self,
        prompt: str,
        *,
        system: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        base_url = normalize_openai_base_url(self.base_url or _OPENAI_BASE_URL)
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        with httpx.Client(timeout=self.timeout_seconds, headers=headers, base_url=base_url.rstrip("/") + "/") as client:
            response = client.post(
                "chat/completions",
                json={
                    "model": self.resolved_model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )
            response.raise_for_status()
            payload = response.json()

        choices = payload.get("choices", [])
        if not choices:
            raise RuntimeError("OpenAI response did not include choices")
        return self._extract_openai_text(choices[0].get("message", {}).get("content"))

    def _generate_claude(
        self,
        prompt: str,
        *,
        system: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        base_url = (self.base_url or _CLAUDE_BASE_URL).rstrip("/")
        headers = {
            "content-type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key

        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(
                f"{base_url}/messages",
                headers=headers,
                json={
                    "model": self.resolved_model,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "system": system,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            response.raise_for_status()
            payload = response.json()

        blocks = payload.get("content", [])
        text_chunks = [block.get("text", "") for block in blocks if isinstance(block, dict)]
        return "\n".join(chunk for chunk in text_chunks if chunk).strip()

    @staticmethod
    def _extract_openai_text(content: Any) -> str:
        """Extract plain text from OpenAI-compatible message content."""
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            return "\n".join(parts).strip()
        return ""

    def generate_json(
        self,
        prompt: str,
        *,
        system: str = "",
        temperature: float = 0.1,
        max_tokens: int = 2500,
    ) -> dict[str, Any] | list[Any]:
        """Generate JSON text and parse it."""
        response = self.generate(
            prompt,
            system=(system + "\n\n" if system else "") + "Respond with valid JSON only.",
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return json.loads(response)

    @staticmethod
    def _messages_to_prompt(messages: list[dict[str, Any]]) -> str:
        """Collapse chat messages into a plain prompt for non-streaming fallbacks."""
        parts: list[str] = []
        for message in messages:
            role = str(message.get("role", "user")).upper()
            content = LLMClient._extract_openai_text(message.get("content"))
            if content:
                parts.append(f"{role}:\n{content}")
        return "\n\n".join(parts).strip()

    @classmethod
    def _parse_stream_line(cls, line: str) -> dict[str, Any] | None:
        """Parse one OpenAI-compatible SSE line into a normalized event."""
        stripped = line.strip()
        if not stripped or stripped.startswith(":"):
            return None
        if stripped.startswith("data:"):
            stripped = stripped[5:].strip()
        if stripped == "[DONE]":
            return None

        payload = json.loads(stripped)
        choices = payload.get("choices", [])
        if not choices:
            return None

        delta = choices[0].get("delta", {})
        content = delta.get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            text = "".join(
                str(item.get("text", ""))
                for item in content
                if isinstance(item, dict)
            )
        else:
            text = ""
        if text:
            return {"type": "text_delta", "delta": text}

        tool_calls = delta.get("tool_calls")
        if tool_calls:
            return {"type": "tool_call_delta", "tool_calls": tool_calls}
        return None
