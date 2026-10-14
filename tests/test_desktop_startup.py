import socket
import urllib.request


def test_backend_readiness_and_shutdown(monkeypatch, isolated_session_root):
    import desktop_app as desktop
    monkeypatch.setattr(desktop, "PORT", 0)
    server, thread = desktop._start_backend()
    try:
        assert desktop._wait_until_ready(server, thread, timeout=5)
        port = server.servers[0].sockets[0].getsockname()[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as response:
            assert response.status == 200
    finally:
        server.should_exit = True
        thread.join(5)
    assert not thread.is_alive()


def test_occupied_port_is_not_accepted_as_ready(monkeypatch, isolated_session_root):
    import desktop_app as desktop
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        monkeypatch.setattr(desktop, "PORT", occupied.getsockname()[1])
        server, thread = desktop._start_backend()
        try:
            assert not desktop._wait_until_ready(server, thread, timeout=3)
        finally:
            server.should_exit = True
            thread.join(5)


def test_window_failure_still_stops_backend(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    import pytest
    import desktop_app as desktop

    server = SimpleNamespace(should_exit=False)
    thread = Mock()
    monkeypatch.setattr(desktop, "_start_backend", lambda: (server, thread))
    monkeypatch.setattr(desktop, "_wait_until_ready", lambda *args: True)
    monkeypatch.setattr(desktop.sys, "argv", ["desktop_app.py"])
    monkeypatch.setattr(desktop.webview, "create_window", Mock(side_effect=RuntimeError("window failed")))
    with pytest.raises(RuntimeError, match="window failed"):
        desktop.main()
    assert server.should_exit
    thread.join.assert_called_once_with(timeout=5)
