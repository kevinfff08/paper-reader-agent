from pathlib import Path
from tempfile import mkdtemp

from fastapi.testclient import TestClient

from backend.app.main import create_app


def test_session_analysis_question_archive_flow(monkeypatch) -> None:
    tmp_path = Path(mkdtemp(prefix="paperreader-flow-", dir=Path.cwd()))
    monkeypatch.setenv("SESSION_DATA_ROOT", str(tmp_path / "sessions"))
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
    assert analyze_response.json()["analysis"]["title"] == "Cross-Paper Synthesis"

    question_response = client.post(
        f"/sessions/{session_id}/questions",
        json={"question": "What should I inspect in the method?", "preferred_paper_ids": []},
    )
    assert question_response.status_code == 200
    assert "Question:" in question_response.json()["qa_record"]["answer_text"]

    archive_response = client.post(
        f"/sessions/{session_id}/archive",
        json={"include_qa": True},
    )
    assert archive_response.status_code == 200

    detail_response = client.get(f"/sessions/{session_id}")
    assert detail_response.status_code == 200
    payload = detail_response.json()
    assert payload["artifacts"]["archive"]["markdown_path"].endswith("archive.md")
    assert len(payload["artifacts"]["analyses"]) >= 2
