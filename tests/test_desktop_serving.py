"""Tests for the desktop-app single-port frontend serving.

The desktop entry point relies on the FastAPI app serving the built React
frontend so the native WebView window can load everything from one origin.
These tests pin that contract: API routes must keep precedence over the static
mount, and the mount must be a no-op when no build output exists.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.main import _mount_frontend


def test_api_routes_take_precedence_over_static_mount(tmp_path: Path) -> None:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "index.html").write_text("<!doctype html><title>PaperReader</title>", encoding="utf-8")

    # Mirror create_app(): register API routes first, then mount static last.
    app = FastAPI()

    @app.get("/healthz")
    def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    _mount_frontend(app, dist_dir=dist_dir)
    client = TestClient(app)

    # Backend API route still resolves rather than being shadowed by "/".
    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}

    # Root serves the built frontend index.
    index = client.get("/")
    assert index.status_code == 200
    assert "PaperReader" in index.text


def test_mount_is_noop_without_build_output(tmp_path: Path) -> None:
    app = FastAPI()
    _mount_frontend(app, dist_dir=tmp_path / "missing-dist")
    assert not any(getattr(route, "name", None) == "frontend" for route in app.routes)
