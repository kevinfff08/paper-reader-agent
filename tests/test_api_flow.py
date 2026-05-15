from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.models.domain import DiscoveredPaper
from backend.app.main import create_app


def test_session_analysis_question_archive_flow(monkeypatch, isolated_session_root: Path) -> None:
    tmp_path = isolated_session_root.parent
    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SESSION_DATA_ROOT", str(isolated_session_root))
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = create_app()
    client = TestClient(app)

    create_response = client.post(
        "/sessions",
        json={"session_name": "Flow Session", "categories": ["ml"], "user_goal": "Read carefully"},
    )
    assert create_response.status_code == 200
    session_id = create_response.json()["session"]["session_id"]

    sample_path = tmp_path / "sample.txt"
    sample_path.write_text(
        "A Great Paper\n\nAbstract This paper studies a simple method.\n\nIntroduction\nWe propose a method.\n\nMethod\nThe method has two stages.\n\nExperiments\nWe evaluate on benchmarks.\n\nConclusion\nThere are limitations.",
        encoding="utf-8",
    )

    with sample_path.open("rb") as handle:
        upload_response = client.post(
            f"/sessions/{session_id}/papers",
            files=[("files", ("sample.txt", handle, "text/plain"))],
        )
    assert upload_response.status_code == 200
    assert len(upload_response.json()["artifacts"]["papers"]) == 1

    analyze_response = client.post(
        f"/sessions/{session_id}/analyze",
        json={"focus_question": "What is the core method?"},
    )
    assert analyze_response.status_code == 200
    assert analyze_response.json()["analysis"]["title"].startswith("Single-Paper Analysis:")

    run_response = client.post(
        f"/sessions/{session_id}/runs",
        json={"mode": "answer", "input": "What do the experiments evaluate?", "preferred_paper_ids": []},
    )
    assert run_response.status_code == 200
    run_id = run_response.json()["run"]["run_id"]

    with client.stream("GET", f"/sessions/{session_id}/runs/{run_id}/events") as response:
        assert response.status_code == 200
        event_stream = "".join(response.iter_text())
    assert '"event_type": "run_started"' in event_stream
    assert '"event_type": "assistant_delta"' in event_stream
    assert '"event_type": "run_completed"' in event_stream

    task_list_response = client.get(f"/sessions/{session_id}/tasks")
    assert task_list_response.status_code == 200
    assert len(task_list_response.json()["tasks"]) >= 1

    question_response = client.post(
        f"/sessions/{session_id}/questions",
        json={"question": "What should I inspect in the method details?", "preferred_paper_ids": []},
    )
    assert question_response.status_code == 200
    assert "Question:" in question_response.json()["qa_record"]["answer_text"]
    assert question_response.json()["qa_record"]["evidence_refs"]
    assert any(item["source_type"] == "paper" for item in question_response.json()["qa_record"]["evidence_refs"])

    archive_response = client.post(
        f"/sessions/{session_id}/archive",
        json={"include_qa": True},
    )
    assert archive_response.status_code == 200
    session_dir = app.state.store.session_dir(session_id)
    assert (session_dir / "archive" / "archive_warnings.json").exists()
    assert (session_dir / "archive" / "archive_warnings.md").exists()

    detail_response = client.get(f"/sessions/{session_id}")
    assert detail_response.status_code == 200
    payload = detail_response.json()
    assert payload["artifacts"]["archive"]["markdown_path"].endswith("archive.md")
    assert len(payload["artifacts"]["analyses"]) >= 1
    assert payload["artifacts"]["runs"]
    assert payload["artifacts"]["compact_summaries"]
    assert payload["artifacts"]["tasks"]
    assert payload["artifacts"]["session_files"]


def test_discovery_and_localize_flow(monkeypatch, isolated_session_root: Path) -> None:
    monkeypatch.setenv("SESSION_DATA_ROOT", str(isolated_session_root))
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app = create_app()
    client = TestClient(app)

    create_response = client.post(
        "/sessions",
        json={"session_name": "Discovery Session", "categories": ["ml"]},
    )
    assert create_response.status_code == 200
    session_id = create_response.json()["session"]["session_id"]

    app.state.search_broker.discover = lambda **kwargs: [  # type: ignore[method-assign]
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
            manual_search_url="https://www.google.com/search?q=attention+is+all+you+need",
            acquisition_status="remote_landing_only",
        )
    ]

    discover_response = client.post(
        f"/sessions/{session_id}/discover",
        json={
            "query": "transformer",
            "discovery_mode": "seminal",
            "domain": "cs",
            "max_results": 5,
            "preferred_venues": [],
        },
    )
    assert discover_response.status_code == 200
    search_id = discover_response.json()["search"]["search_id"]
    assert discover_response.json()["search"]["results"][0]["title"] == "Attention Is All You Need"

    history_response = client.get(f"/sessions/{session_id}/discover")
    assert history_response.status_code == 200
    assert history_response.json()["searches"][0]["search_id"] == search_id

    localize_response = client.post(
        f"/sessions/{session_id}/discover/{search_id}/localize",
        json={"result_id": "result-1"},
    )
    assert localize_response.status_code == 200
    assert localize_response.json()["reference"]["title"] == "Attention Is All You Need"

    detail_response = client.get(f"/sessions/{session_id}")
    assert detail_response.status_code == 200
    assert detail_response.json()["artifacts"]["references"][0]["title"] == "Attention Is All You Need"
    assert detail_response.json()["artifacts"]["literature_searches"][0]["query"] == "transformer"
