import json
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
from unittest.mock import Mock

import pytest

from backend.app.core.config import Settings
import desktop_proxy


def test_ready_proxy_is_reused_without_starting_process(monkeypatch):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.path == "/v1/models"
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"data": []}).encode())

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    launch = Mock(side_effect=AssertionError("must reuse existing proxy"))
    monkeypatch.setattr(desktop_proxy.subprocess, "Popen", launch)
    try:
        desktop_proxy.ensure_proxy(Settings(llm_mode="setup-token", llm_proxy_url=f"http://127.0.0.1:{server.server_port}"))
        launch.assert_not_called()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def test_unavailable_custom_proxy_does_not_launch_wrong_service(monkeypatch):
    monkeypatch.setattr(desktop_proxy, "_proxy_ready", lambda *args: False)
    launch = Mock()
    monkeypatch.setattr(desktop_proxy.subprocess, "Popen", launch)
    with pytest.raises(RuntimeError, match="Configured proxy is unavailable"):
        desktop_proxy.ensure_proxy(Settings(llm_mode="setup-token", llm_proxy_url="http://127.0.0.1:9999"))
    launch.assert_not_called()


def test_proxy_start_timeout_cleans_up_owned_process(monkeypatch):
    monkeypatch.setattr(desktop_proxy, "_proxy_ready", lambda *args: False)
    monkeypatch.setattr(desktop_proxy.Path, "is_file", lambda self: True)
    process = Mock()
    process.poll.return_value = None
    monkeypatch.setattr(desktop_proxy.subprocess, "Popen", Mock(return_value=process))
    with pytest.raises(RuntimeError, match="timeout"):
        desktop_proxy.ensure_proxy(Settings(llm_mode="setup-token", llm_proxy_url="http://localhost:8317"), timeout=0)
    process.terminate.assert_called_once()
    process.wait.assert_called_once_with(timeout=3)
