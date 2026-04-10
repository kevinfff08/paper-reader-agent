from datetime import UTC, datetime
from pathlib import Path
from tempfile import mkdtemp

from backend.app.models.domain import MemoryNote
from backend.app.storage.session_store import SessionStore


def _workspace_temp_dir() -> Path:
    base = Path(mkdtemp(prefix="paperreader-tests-", dir=Path.cwd()))
    return base


def test_session_store_creates_expected_structure() -> None:
    store = SessionStore(_workspace_temp_dir() / "sessions")
    session = store.create_session(
        session_name="Test Session",
        categories=["nlp", "reading"],
        user_goal="Understand the method",
        background=None,
        external_links=[],
    )

    session_dir = store.session_dir(session.session_id)
    for folder in ("uploads", "parsed", "references", "analysis", "qa", "memory", "archive", "logs"):
        assert (session_dir / folder).exists()


def test_session_store_saves_memory_markdown() -> None:
    store = SessionStore(_workspace_temp_dir() / "sessions")
    session = store.create_session(
        session_name="Memory Session",
        categories=[],
        user_goal=None,
        background=None,
        external_links=[],
    )
    note = MemoryNote(
        session_id=session.session_id,
        path="",
        confirmed_points=["Point A"],
        unresolved_points=["Point B"],
        tracked_questions=["Why?"],
        paper_titles=["Paper 1"],
        reference_titles=["Reference 1"],
        updated_at=datetime.now(UTC),
    )
    store.save_memory(session.session_id, note)

    memory_path = store.session_dir(session.session_id) / "memory" / "memory.md"
    assert memory_path.exists()
    assert "Point A" in memory_path.read_text(encoding="utf-8")
