"""Optional local CLIProxy startup checks for the desktop shell."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from backend.app.core.config import Settings


def _proxy_ready(url: str, api_key: str | None) -> bool:
    base = url.rstrip("/")
    endpoint = base + ("/models" if base.endswith("/v1") else "/v1/models")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        with urlopen(Request(endpoint, headers=headers), timeout=1) as response:
            payload = json.load(response)
            if isinstance(payload, dict) and isinstance(payload.get("data"), list):
                return True
            raise RuntimeError("Proxy returned an unexpected models response.")
    except HTTPError as exc:
        raise RuntimeError(f"Proxy readiness request failed (HTTP {exc.code}); check proxy configuration and credentials.") from exc
    except (URLError, TimeoutError, ConnectionError):
        return False
    except ValueError as exc:
        raise RuntimeError("Proxy did not return valid model metadata.") from exc


def ensure_proxy(settings: Settings, timeout: float = 15.0) -> None:
    """Reuse a ready proxy, or start the supported local installation and verify it."""
    if settings.llm_mode != "setup-token":
        return
    url = settings.llm_proxy_url
    if not url:
        raise RuntimeError("LLM_PROXY_URL is required for setup-token mode.")
    key = settings.openai_api_key if settings.llm_provider == "openai" else settings.claude_api_key
    if _proxy_ready(url, key):
        print("[OK] Existing proxy is ready.")
        return
    address = urlsplit(url)
    if address.hostname not in {"localhost", "127.0.0.1"} or address.port != 8317:
        raise RuntimeError("Configured proxy is unavailable. Start that service and retry; automatic startup supports localhost:8317 only.")
    executable = Path(r"C:\cliproxyapi\cli-proxy-api.exe")
    config = executable.with_name("config.yaml")
    if not executable.is_file() or not config.is_file():
        raise RuntimeError("Local proxy is unavailable; expected CLIProxyAPI and config.yaml in C:\\cliproxyapi.")
    process = subprocess.Popen(
        [str(executable), "--config", str(config)], cwd=executable.parent,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    try:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"Local proxy exited during startup (code {process.returncode}).")
            if _proxy_ready(url, key):
                print("[OK] Local proxy is ready.")
                return
            time.sleep(0.2)
        raise RuntimeError("Local proxy did not become ready within the startup timeout.")
    except BaseException:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
        raise
