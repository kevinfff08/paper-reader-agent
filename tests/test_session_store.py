from datetime import UTC, datetime
from pathlib import Path

from backend.app.core.models.domain import CompactSummary, DiscoveredPaper, EvidenceLedgerEntry, LiteratureSearchRecord, MemoryNote, RunEvent, RunSummary
from backend.app.storage.session_store import SessionStore


def test_session_store_creates_expected_structure(isolated_session_root) -> None:
    store = SessionStore(isolated_session_root)
    session = store.create_session(
        session_name="Test Session",
        categories=["nlp", "reading"],
        user_goal="Understand the method",
        background=None,
        external_links=[],
    )

    session_dir = store.session_dir(session.session_id)
    for folder in (
        "uploads",
        "parsed",
        "references",
        "searches",
        "analysis",
        "qa",
        "memory",
        "memory/evidence",
        "memory/compact",
        "archive",
        "logs",
        "runs",
    ):
        assert (session_dir / folder).exists()


def test_session_store_saves_memory_markdown(isolated_session_root) -> None:
    store = SessionStore(isolated_session_root)
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


def test_session_store_persists_run_and_layered_memory(isolated_session_root) -> None:
    store = SessionStore(isolated_session_root)
    session = store.create_session(
        session_name="Run Session",
        categories=[],
        user_goal=None,
        background=None,
        external_links=[],
    )
    now = datetime.now(UTC)
    run = RunSummary(
        run_id="run-123",
        session_id=session.session_id,
        mode="answer",
        status="running",
        input_text="What does the method do?",
        created_at=now,
        updated_at=now,
    )
    store.create_run(run)
    store.append_run_event(
        session.session_id,
        RunEvent(
            event_id="evt-123",
            run_id=run.run_id,
            sequence_number=1,
            event_type="run_started",
            payload={"mode": "answer"},
            created_at=now,
        ),
    )
    store.save_evidence_entry(
        session.session_id,
        EvidenceLedgerEntry(
            evidence_id="ev-123",
            session_id=session.session_id,
            run_id=run.run_id,
            source_type="paper",
            asset_id="paper-1",
            label="Method section",
            excerpt="The method has two stages.",
            locator="Method",
            recorded_at=now,
        ),
    )
    store.save_compact_summary(
        session.session_id,
        CompactSummary(
            summary_id="sum-123",
            session_id=session.session_id,
            boundary_label="qa:method",
            content="The answer established the two-stage method.",
            created_at=now,
        ),
    )

    artifacts = store.get_artifacts(session.session_id)
    assert artifacts.runs[0].run_id == "run-123"
    assert artifacts.evidence_ledger[0].label == "Method section"
    assert artifacts.compact_summaries[0].boundary_label == "qa:method"
    assert store.list_run_events(session.session_id, "run-123")[0].event_type == "run_started"


def test_session_store_persists_literature_searches(isolated_session_root) -> None:
    store = SessionStore(isolated_session_root)
    session = store.create_session(
        session_name="Search Session",
        categories=[],
        user_goal=None,
        background=None,
        external_links=[],
    )
    now = datetime.now(UTC)
    search = LiteratureSearchRecord(
        search_id="search-123",
        session_id=session.session_id,
        query="transformer interpretability",
        discovery_mode="seminal",
        domain="cs",
        preferred_venues=["NeurIPS"],
        results=[
            DiscoveredPaper(
                result_id="result-1",
                title="Attention Is All You Need",
                authors=["Ashish Vaswani"],
                year=2017,
                venue="NeurIPS",
                source_kind="openalex",
                source_url="https://example.org/paper",
                citation_count=1000,
                summary="A seminal transformer paper.",
                landing_page_url="https://example.org/paper",
                best_access_url="https://example.org/paper",
                acquisition_status="remote_landing_only",
            )
        ],
        created_at=now,
    )
    store.save_literature_search(session.session_id, search)

    loaded = store.get_literature_search(session.session_id, "search-123")
    artifacts = store.get_artifacts(session.session_id)
    assert loaded.query == "transformer interpretability"
    assert loaded.results[0].title == "Attention Is All You Need"
    assert artifacts.literature_searches[0].search_id == "search-123"


def test_session_store_rejects_formal_root_in_test_mode(monkeypatch) -> None:
    monkeypatch.setenv("PAPERREADER_TEST_MODE", "1")
    monkeypatch.setenv("SESSION_DATA_ROOT", "data/sessions")

    try:
        SessionStore(Path("data/sessions"))
    except ValueError as exc:
        assert "formal data/sessions" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("SessionStore should reject the formal session root in test mode")
