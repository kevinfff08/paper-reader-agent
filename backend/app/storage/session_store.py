"""Filesystem-backed session store."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar
from uuid import uuid4

from backend.app.logging.session_logger import get_session_logger
from backend.app.models.domain import (
    AnalysisArtifact,
    ArchiveArtifact,
    MemoryNote,
    PaperAsset,
    ParsedDocument,
    QARecord,
    ReferenceAsset,
    SessionArtifacts,
    SessionSummary,
    TaskStatus,
)


T = TypeVar("T")


class SessionStore:
    """Persist session data to the local filesystem."""

    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def create_session(
        self,
        *,
        session_name: str,
        categories: list[str],
        user_goal: str | None,
        background: str | None,
        external_links: list[str],
    ) -> SessionSummary:
        now = datetime.now(UTC)
        slug = self._slugify(session_name)
        created_label = now.strftime("%Y%m%d_%H%M%S")
        session_id = f"{slug}-{created_label}"
        session_dir = self.root / f"{slug}__{created_label}"
        for child in ("uploads", "parsed", "references", "analysis", "qa", "memory", "archive", "logs"):
            (session_dir / child).mkdir(parents=True, exist_ok=True)

        summary = SessionSummary(
            session_id=session_id,
            session_name=session_name,
            session_slug=slug,
            categories=categories,
            user_goal=user_goal,
            background=background,
            external_links=external_links,
            created_at=now,
            updated_at=now,
            latest_task=None,
        )
        self._write_model(session_dir / "session.json", summary)
        self._write_json(session_dir / "papers.json", [])
        self._write_json(session_dir / "references.json", [])
        self._write_json(session_dir / "analysis_index.json", [])
        self._write_json(session_dir / "qa_index.json", [])
        logger = get_session_logger(session_dir, slug, created_label)
        logger.info("Session created: %s", session_name)
        self.save_memory(
            session_id,
            MemoryNote(
                session_id=session_id,
                path=str(session_dir / "memory" / "memory.md"),
                updated_at=now,
            ),
        )
        return summary

    def list_sessions(self) -> list[SessionSummary]:
        sessions: list[SessionSummary] = []
        for path in sorted(self.root.glob("*"), reverse=True):
            session_file = path / "session.json"
            if session_file.exists():
                sessions.append(SessionSummary.model_validate_json(session_file.read_text(encoding="utf-8")))
        return sessions

    def get_session(self, session_id: str) -> SessionSummary:
        session_dir = self.session_dir(session_id)
        return SessionSummary.model_validate_json((session_dir / "session.json").read_text(encoding="utf-8"))

    def update_session(self, session: SessionSummary) -> None:
        self._write_model(self.session_dir(session.session_id) / "session.json", session)

    def session_dir(self, session_id: str) -> Path:
        for path in self.root.glob("*"):
            session_file = path / "session.json"
            if not session_file.exists():
                continue
            session = SessionSummary.model_validate_json(session_file.read_text(encoding="utf-8"))
            if session.session_id == session_id:
                return path
        raise FileNotFoundError(f"Session not found: {session_id}")

    def append_task(self, session_id: str, task: TaskStatus) -> None:
        session = self.get_session(session_id)
        session.latest_task = task
        session.updated_at = datetime.now(UTC)
        self.update_session(session)
        session_dir = self.session_dir(session_id)
        task_path = session_dir / "tasks.json"
        tasks = self._read_json(task_path, [])
        tasks.append(task.model_dump(mode="json"))
        self._write_json(task_path, tasks)

    def save_uploaded_paper(self, session_id: str, *, filename: str, media_type: str, content: bytes) -> PaperAsset:
        session_dir = self.session_dir(session_id)
        paper_id = uuid4().hex[:12]
        upload_path = session_dir / "uploads" / f"{paper_id}_{filename}"
        upload_path.write_bytes(content)
        paper = PaperAsset(
            paper_id=paper_id,
            filename=filename,
            media_type=media_type,
            original_path=str(upload_path),
            created_at=datetime.now(UTC),
        )
        papers = self.list_papers(session_id)
        papers.append(paper)
        self._write_json(session_dir / "papers.json", [item.model_dump(mode="json") for item in papers])
        return paper

    def list_papers(self, session_id: str) -> list[PaperAsset]:
        payload = self._read_json(self.session_dir(session_id) / "papers.json", [])
        return [PaperAsset.model_validate(item) for item in payload]

    def save_parsed_document(self, session_id: str, parsed_doc: ParsedDocument) -> ParsedDocument:
        session_dir = self.session_dir(session_id)
        path = session_dir / "parsed" / f"{parsed_doc.paper_id}.json"
        self._write_model(path, parsed_doc)
        papers = self.list_papers(session_id)
        for paper in papers:
            if paper.paper_id == parsed_doc.paper_id:
                paper.parsed_path = str(path)
                paper.title = parsed_doc.title
        self._write_json(session_dir / "papers.json", [item.model_dump(mode="json") for item in papers])
        return parsed_doc

    def load_parsed_documents(self, session_id: str) -> list[ParsedDocument]:
        session_dir = self.session_dir(session_id)
        return [
            ParsedDocument.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted((session_dir / "parsed").glob("*.json"))
        ]

    def save_analysis(self, session_id: str, analysis: AnalysisArtifact) -> AnalysisArtifact:
        session_dir = self.session_dir(session_id)
        path = session_dir / "analysis" / f"{analysis.analysis_id}.json"
        self._write_model(path, analysis)
        index = self._read_json(session_dir / "analysis_index.json", [])
        index.append(analysis.model_dump(mode="json"))
        self._write_json(session_dir / "analysis_index.json", index)
        return analysis

    def list_analyses(self, session_id: str) -> list[AnalysisArtifact]:
        payload = self._read_json(self.session_dir(session_id) / "analysis_index.json", [])
        return [AnalysisArtifact.model_validate(item) for item in payload]

    def save_reference(self, session_id: str, reference: ReferenceAsset) -> ReferenceAsset:
        session_dir = self.session_dir(session_id)
        index = self._read_json(session_dir / "references.json", [])
        index.append(reference.model_dump(mode="json"))
        self._write_json(session_dir / "references.json", index)
        return reference

    def list_references(self, session_id: str) -> list[ReferenceAsset]:
        payload = self._read_json(self.session_dir(session_id) / "references.json", [])
        return [ReferenceAsset.model_validate(item) for item in payload]

    def save_qa_record(self, session_id: str, qa_record: QARecord) -> QARecord:
        session_dir = self.session_dir(session_id)
        index = self._read_json(session_dir / "qa_index.json", [])
        index.append(qa_record.model_dump(mode="json"))
        self._write_json(session_dir / "qa_index.json", index)
        return qa_record

    def list_qa_records(self, session_id: str) -> list[QARecord]:
        payload = self._read_json(self.session_dir(session_id) / "qa_index.json", [])
        return [QARecord.model_validate(item) for item in payload]

    def save_memory(self, session_id: str, memory: MemoryNote) -> MemoryNote:
        session_dir = self.session_dir(session_id)
        md_path = session_dir / "memory" / "memory.md"
        md_path.write_text(self._render_memory_markdown(memory), encoding="utf-8")
        json_path = session_dir / "memory" / "memory.json"
        self._write_model(json_path, memory)
        return memory

    def load_memory(self, session_id: str) -> MemoryNote | None:
        path = self.session_dir(session_id) / "memory" / "memory.json"
        if not path.exists():
            return None
        return MemoryNote.model_validate_json(path.read_text(encoding="utf-8"))

    def save_archive(self, session_id: str, archive: ArchiveArtifact, markdown: str) -> ArchiveArtifact:
        session_dir = self.session_dir(session_id)
        md_path = session_dir / "archive" / "archive.md"
        md_path.write_text(markdown, encoding="utf-8")
        archive = archive.model_copy(update={"markdown_path": str(md_path)})
        self._write_model(session_dir / "archive" / "archive.json", archive)
        return archive

    def load_archive(self, session_id: str) -> ArchiveArtifact | None:
        path = self.session_dir(session_id) / "archive" / "archive.json"
        if not path.exists():
            return None
        return ArchiveArtifact.model_validate_json(path.read_text(encoding="utf-8"))

    def get_artifacts(self, session_id: str) -> SessionArtifacts:
        return SessionArtifacts(
            papers=self.list_papers(session_id),
            references=self.list_references(session_id),
            analyses=self.list_analyses(session_id),
            qa_records=self.list_qa_records(session_id),
            memory=self.load_memory(session_id),
            archive=self.load_archive(session_id),
        )

    def _render_memory_markdown(self, memory: MemoryNote) -> str:
        lines = [
            f"# Memory Note: {memory.session_id}",
            "",
            "## Confirmed Points",
            *([f"- {item}" for item in memory.confirmed_points] or ["- None"]),
            "",
            "## Unresolved Points",
            *([f"- {item}" for item in memory.unresolved_points] or ["- None"]),
            "",
            "## Tracked Questions",
            *([f"- {item}" for item in memory.tracked_questions] or ["- None"]),
            "",
            "## Papers",
            *([f"- {item}" for item in memory.paper_titles] or ["- None"]),
            "",
            "## References",
            *([f"- {item}" for item in memory.reference_titles] or ["- None"]),
            "",
        ]
        return "\n".join(lines)

    def _read_json(self, path: Path, default: list[dict] | list[str] | list | dict) -> list | dict:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_json(self, path: Path, payload: list | dict) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_model(self, path: Path, model: object) -> None:
        if hasattr(model, "model_dump_json"):
            path.write_text(model.model_dump_json(indent=2), encoding="utf-8")  # type: ignore[attr-defined]
        else:
            raise TypeError("Unsupported model type")

    def _slugify(self, value: str) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
        return cleaned or "session"
