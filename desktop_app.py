"""Desktop entry point for PaperReader.

Runs the existing FastAPI backend in-process and shows the React frontend in a
native OS WebView window (Edge WebView2 on Windows via ``pywebview``). This keeps
the full backend workflow, SSE streaming, and ``data/`` persistence unchanged --
the only difference from the server/browser setup is that everything lives in a
single process behind one window.

Usage:
    python desktop_app.py            # serve the built frontend (frontend/dist)
    python desktop_app.py --dev      # point the window at the Vite dev server

In ``--dev`` mode the backend still starts here on the same port; run
``npm run dev`` separately to get frontend hot-reload at http://127.0.0.1:5173.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import urllib.error
import urllib.request

import uvicorn
import webview

HOST: str = os.getenv("PAPERREADER_DESKTOP_HOST", "127.0.0.1")
PORT: int = int(os.getenv("PAPERREADER_DESKTOP_PORT", "8000"))
DEV_URL: str = os.getenv("PAPERREADER_DESKTOP_DEV_URL", "http://127.0.0.1:5173")
WINDOW_TITLE: str = "PaperReader"


class _BackgroundServer(uvicorn.Server):
    """Uvicorn server that can run inside a worker thread.

    Signal handlers are only installable on the main thread, so they are
    disabled here; shutdown is driven explicitly via ``should_exit``.
    """

    def install_signal_handlers(self) -> None:  # noqa: D401 - override
        return None


def _start_backend() -> tuple[_BackgroundServer, threading.Thread]:
    """Launch the FastAPI app on a daemon thread and return its handles."""
    # Imported lazily so backend construction (and its env checks) happens only
    # when we actually start the desktop app.
    from backend.app.main import app

    config = uvicorn.Config(app, host=HOST, port=PORT, log_level="info")
    server = _BackgroundServer(config)
    thread = threading.Thread(target=server.run, name="paperreader-backend", daemon=True)
    thread.start()
    return server, thread


def _wait_until_ready(timeout: float = 60.0) -> bool:
    """Poll ``/healthz`` until the backend responds or the timeout elapses."""
    health_url = f"http://{HOST}:{PORT}/healthz"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=2) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.25)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Run PaperReader as a desktop app.")
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Point the window at the Vite dev server (run `npm run dev` separately).",
    )
    args = parser.parse_args()

    server, _thread = _start_backend()
    if not _wait_until_ready():
        print("[ERROR] Backend did not become ready in time; aborting.", file=sys.stderr)
        server.should_exit = True
        return 1

    target_url = DEV_URL if args.dev else f"http://{HOST}:{PORT}"
    print(f"[OK] PaperReader backend ready. Opening window at {target_url}")

    webview.create_window(WINDOW_TITLE, target_url, width=1280, height=860)
    # Blocks until every window is closed.
    webview.start()

    # Window closed -> shut the backend down and let the process exit cleanly.
    server.should_exit = True
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
