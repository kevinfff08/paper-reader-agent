from __future__ import annotations

from pathlib import Path
import sys
from uuid import uuid4

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def make_test_workspace(label: str) -> Path:
    """Return a dedicated test-only workspace under .tmp-tests."""
    path = Path.cwd() / ".tmp-tests" / "session-data" / f"{label}-{uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture(autouse=True)
def enforce_test_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force protected test mode for every test process."""
    monkeypatch.setenv("PAPERREADER_TEST_MODE", "1")


@pytest.fixture
def isolated_session_root(monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provide a session root that is isolated from formal app data."""
    root = make_test_workspace("sessions") / "sessions"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SESSION_DATA_ROOT", str(root))
    return root
