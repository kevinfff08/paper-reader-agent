"""Filesystem-backed session store."""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar
from uuid import uuid4

from backend.app.core.config import ensure_safe_session_root, is_test_mode_enabled
from backend.app.core.models.domain import (
    AnalysisArtifact,
    ArchiveArtifact,
    CompactSummary,
    EvidenceLedgerEntry,
    LibraryCard,
    LiteratureSearchRecord,
    MemoryNote,
    PaperAsset,
    ParsedDocument,
    QARecord,
    ReferenceAsset,
    RunEvent,
    RunSummary,
    SessionFileEntry,
    SessionArtifacts,
    SessionSummary,
    TaskEvent,
    TaskSummary,
    VerificationNote,
    WorkingStateSnapshot,
)
from backend.app.logging.session_logger import get_session_logger


T = TypeVar("T")


class SessionStore:
    """Persist session data to the local filesystem."""

    def __init__(self, root: Path, *, test_mode: bool | None = None):
        self.root = root
        self.test_mode = is_test_mode_enabled() if test_mode is None else test_mode
        self._io_lock = threading.RLock()
        ensure_safe_session_root(self.root, test_mode=self.test_mode)
        self.root.mkdir(parents=True, exist_ok=True)
        self.library_root = self.root / "_library"
        self.library_root.mkdir(parents=True, exist_ok=True)

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
        for child in (
            "uploads",
            "parsed",
            "references",
            "searches",
            "analysis",
            "qa",
            "memory",
            "memory/evidence",
            "memory/compact",
            "memory/verification",
            "archive",
            "logs",
            "runs",
            "tasks",
        ):
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
        )
        self._write_model(session_dir / "session.json", summary)
        self._write_json(session_dir / "papers.json", [])
        self._write_json(session_dir / "references.json", [])
        self._write_json(session_dir / "searches" / "index.json", [])
        self._write_json(session_dir / "analysis_index.json", [])
        self._write_json(session_dir / "qa_index.json", [])
        self._write_json(session_dir / "runs" / "index.json", [])
        self._write_json(session_dir / "tasks" / "index.json", [])
        self._write_json(session_dir / "memory" / "compact" / "summaries.json", [])
        self._write_json(session_dir / "memory" / "verification" / "notes.json", [])
        self._write_json(session_dir / "memory" / "working_state.json", {"version": 0})
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
                sessions.append(self._read_model_json(session_file, SessionSummary))
        return sessions

    def get_session(self, session_id: str) -> SessionSummary:
        session_dir = self.session_dir(session_id)
        return self._read_model_json(session_dir / "session.json", SessionSummary)

    def update_session(self, session: SessionSummary) -> None:
        self._write_model(self.session_dir(session.session_id) / "session.json", session)

    def session_dir(self, session_id: str) -> Path:
        for path in self.root.glob("*"):
            session_file = path / "session.json"
            if not session_file.exists():
                continue
            session = self._read_model_json(session_file, SessionSummary)
            if session.session_id == session_id:
                return path
        raise FileNotFoundError(f"Session not found: {session_id}")

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
            self._read_model_json(path, ParsedDocument)
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

    def save_literature_search(self, session_id: str, search: LiteratureSearchRecord) -> LiteratureSearchRecord:
        session_dir = self.session_dir(session_id)
        path = session_dir / "searches" / f"{search.search_id}.json"
        self._write_model(path, search)
        index_path = session_dir / "searches" / "index.json"
        index = self._read_json(index_path, [])
        index.append(
            {
                "search_id": search.search_id,
                "session_id": search.session_id,
                "query": search.query,
                "discovery_mode": search.discovery_mode,
                "domain": search.domain,
                "preferred_venues": search.preferred_venues,
                "created_at": search.created_at.isoformat(),
                "result_count": len(search.results),
            }
        )
        self._write_json(index_path, index)
        return search

    def list_literature_searches(self, session_id: str) -> list[LiteratureSearchRecord]:
        searches_dir = self.session_dir(session_id) / "searches"
        return [
            self._read_model_json(path, LiteratureSearchRecord)
            for path in sorted(searches_dir.glob("*.json"))
            if path.name != "index.json"
        ]

    def get_literature_search(self, session_id: str, search_id: str) -> LiteratureSearchRecord:
        path = self.session_dir(session_id) / "searches" / f"{search_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"Search not found: {search_id}")
        return self._read_model_json(path, LiteratureSearchRecord)

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
        return self._read_model_json(path, MemoryNote)

    def save_evidence_entry(self, session_id: str, entry: EvidenceLedgerEntry) -> EvidenceLedgerEntry:
        path = self.session_dir(session_id) / "memory" / "evidence" / "ledger.jsonl"
        self._append_jsonl(path, entry.model_dump(mode="json"))
        return entry

    def list_evidence_entries(self, session_id: str) -> list[EvidenceLedgerEntry]:
        path = self.session_dir(session_id) / "memory" / "evidence" / "ledger.jsonl"
        return [EvidenceLedgerEntry.model_validate(item) for item in self._read_jsonl(path)]

    def save_compact_summary(self, session_id: str, summary: CompactSummary) -> CompactSummary:
        path = self.session_dir(session_id) / "memory" / "compact" / "summaries.json"
        payload = self._read_json(path, [])
        payload.append(summary.model_dump(mode="json"))
        self._write_json(path, payload)
        return summary

    def list_compact_summaries(self, session_id: str) -> list[CompactSummary]:
        path = self.session_dir(session_id) / "memory" / "compact" / "summaries.json"
        payload = self._read_json(path, [])
        return [CompactSummary.model_validate(item) for item in payload]

    def save_library_card(self, card: LibraryCard) -> LibraryCard:
        path = self.library_root / "cards.json"
        payload = self._read_json(path, [])
        payload.append(card.model_dump(mode="json"))
        self._write_json(path, payload)
        return card

    def list_library_cards(self, session_id: str | None = None) -> list[LibraryCard]:
        payload = self._read_json(self.library_root / "cards.json", [])
        cards = [LibraryCard.model_validate(item) for item in payload]
        if session_id is None:
            return cards
        return [card for card in cards if card.session_id == session_id]

    def load_working_state_version(self, session_id: str) -> int:
        payload = self._read_json(self.session_dir(session_id) / "memory" / "working_state.json", {"version": 0})
        if isinstance(payload, dict):
            return int(payload.get("version", 0))
        return 0

    def bump_working_state_version(self, session_id: str) -> int:
        version = self.load_working_state_version(session_id) + 1
        self._write_json(self.session_dir(session_id) / "memory" / "working_state.json", {"version": version})
        return version

    def save_working_snapshot(self, session_id: str, snapshot: WorkingStateSnapshot) -> WorkingStateSnapshot:
        path = self.session_dir(session_id) / "tasks" / f"{snapshot.snapshot_id}.snapshot.json"
        self._write_model(path, snapshot)
        return snapshot

    def get_working_snapshot(self, session_id: str, snapshot_id: str) -> WorkingStateSnapshot:
        path = self.session_dir(session_id) / "tasks" / f"{snapshot_id}.snapshot.json"
        if not path.exists():
            raise FileNotFoundError(f"Working snapshot not found: {snapshot_id}")
        return self._read_model_json(path, WorkingStateSnapshot)

    def save_verification_note(self, session_id: str, note: VerificationNote) -> VerificationNote:
        path = self.session_dir(session_id) / "memory" / "verification" / "notes.json"
        payload = self._read_json(path, [])
        payload.append(note.model_dump(mode="json"))
        self._write_json(path, payload)
        return note

    def list_verification_notes(self, session_id: str) -> list[VerificationNote]:
        path = self.session_dir(session_id) / "memory" / "verification" / "notes.json"
        payload = self._read_json(path, [])
        return [VerificationNote.model_validate(item) for item in payload]

    def create_task(self, task: TaskSummary) -> TaskSummary:
        session_dir = self.session_dir(task.session_id)
        path = session_dir / "tasks" / f"{task.task_id}.json"
        self._write_model(path, task)
        index_path = session_dir / "tasks" / "index.json"
        index = self._read_json(index_path, [])
        index.append(task.model_dump(mode="json"))
        self._write_json(index_path, index)
        return task

    def update_task(self, session_id: str, task: TaskSummary) -> TaskSummary:
        session_dir = self.session_dir(session_id)
        path = session_dir / "tasks" / f"{task.task_id}.json"
        self._write_model(path, task)
        index_path = session_dir / "tasks" / "index.json"
        index = [
            task.model_dump(mode="json") if item.get("task_id") == task.task_id else item
            for item in self._read_json(index_path, [])
        ]
        self._write_json(index_path, index)
        return task

    def get_task(self, session_id: str, task_id: str) -> TaskSummary:
        path = self.session_dir(session_id) / "tasks" / f"{task_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"Task not found: {task_id}")
        return self._read_model_json(path, TaskSummary)

    def list_tasks(self, session_id: str) -> list[TaskSummary]:
        payload = self._read_json(self.session_dir(session_id) / "tasks" / "index.json", [])
        return [TaskSummary.model_validate(item) for item in payload]

    def append_task_event(self, session_id: str, event: TaskEvent) -> TaskEvent:
        path = self.session_dir(session_id) / "tasks" / f"{event.task_id}.events.jsonl"
        self._append_jsonl(path, event.model_dump(mode="json"))
        return event

    def list_task_events(self, session_id: str, task_id: str) -> list[TaskEvent]:
        path = self.session_dir(session_id) / "tasks" / f"{task_id}.events.jsonl"
        return [TaskEvent.model_validate(item) for item in self._read_jsonl(path)]

    def create_run(self, run: RunSummary) -> RunSummary:
        session_dir = self.session_dir(run.session_id)
        path = session_dir / "runs" / f"{run.run_id}.json"
        self._write_model(path, run)
        index_path = session_dir / "runs" / "index.json"
        index = self._read_json(index_path, [])
        index.append(run.model_dump(mode="json"))
        self._write_json(index_path, index)
        return run

    def update_run(self, session_id: str, run: RunSummary) -> RunSummary:
        session_dir = self.session_dir(session_id)
        path = session_dir / "runs" / f"{run.run_id}.json"
        self._write_model(path, run)
        index_path = session_dir / "runs" / "index.json"
        index = [
            run.model_dump(mode="json") if item.get("run_id") == run.run_id else item
            for item in self._read_json(index_path, [])
        ]
        self._write_json(index_path, index)
        return run

    def get_run(self, session_id: str, run_id: str) -> RunSummary:
        path = self.session_dir(session_id) / "runs" / f"{run_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"Run not found: {run_id}")
        return self._read_model_json(path, RunSummary)

    def list_runs(self, session_id: str) -> list[RunSummary]:
        payload = self._read_json(self.session_dir(session_id) / "runs" / "index.json", [])
        return [RunSummary.model_validate(item) for item in payload]

    def append_run_event(self, session_id: str, event: RunEvent) -> RunEvent:
        path = self.session_dir(session_id) / "runs" / f"{event.run_id}.events.jsonl"
        self._append_jsonl(path, event.model_dump(mode="json"))
        return event

    def list_run_events(self, session_id: str, run_id: str) -> list[RunEvent]:
        path = self.session_dir(session_id) / "runs" / f"{run_id}.events.jsonl"
        return [RunEvent.model_validate(item) for item in self._read_jsonl(path)]

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
        return self._read_model_json(path, ArchiveArtifact)

    def get_artifacts(self, session_id: str) -> SessionArtifacts:
        return SessionArtifacts(
            papers=self.list_papers(session_id),
            references=self.list_references(session_id),
            analyses=self.list_analyses(session_id),
            qa_records=self.list_qa_records(session_id),
            memory=self.load_memory(session_id),
            evidence_ledger=self.list_evidence_entries(session_id),
            compact_summaries=self.list_compact_summaries(session_id),
            library_cards=self.list_library_cards(session_id),
            verification_memory=self.list_verification_notes(session_id),
            literature_searches=self.list_literature_searches(session_id),
            runs=self.list_runs(session_id),
            tasks=self.list_tasks(session_id),
            session_files=self.list_session_files(session_id),
            archive=self.load_archive(session_id),
        )

    def list_session_files(self, session_id: str) -> list[SessionFileEntry]:
        session_dir = self.session_dir(session_id)
        entries: list[SessionFileEntry] = []
        patterns: list[tuple[str, str, str, bool]] = [
            ("uploads", "*.pdf", "paper", False),
            ("uploads", "*.txt", "paper", False),
            ("parsed", "*.json", "parsed", True),
            ("parsed", "*.md", "parsed", True),
            ("references", "*.md", "reference", False),
            ("analysis", "*.md", "analysis", False),
            ("analysis", "*.json", "analysis", False),
            ("archive", "*.md", "archive", False),
            ("memory", "memory.md", "memory", False),
            ("memory/evidence", "ledger.jsonl", "memory", False),
            ("memory/compact", "summaries.json", "memory", False),
            ("memory/verification", "notes.json", "memory", False),
            ("tasks", "*.json", "task", False),
        ]
        for folder, pattern, category, recursive in patterns:
            root = session_dir / folder
            iterator = root.rglob(pattern) if recursive else root.glob(pattern)
            for path in sorted(iterator):
                if path.name == "index.json" or path.name.endswith(".events.jsonl") or path.name.endswith(".snapshot.json"):
                    continue
                entries.append(
                    SessionFileEntry(
                        file_id=str(path),
                        label=path.name,
                        path=str(path),
                        category=category,  # type: ignore[arg-type]
                        updated_at=datetime.fromtimestamp(path.stat().st_mtime, tz=UTC),
                    )
                )
        return sorted(entries, key=lambda item: (item.category, item.label.lower()))

    def _render_memory_markdown(self, memory: MemoryNote) -> str:
        lines = [
            f"# Working Memory: {memory.session_id}",
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
        with self._io_lock:
            if not path.exists():
                return default
            last_error: Exception | None = None
            for _ in range(5):
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except ValueError as exc:
                    last_error = exc
                    time.sleep(0.02)
            raise last_error or RuntimeError(f"Unable to read json file: {path}")

    def _write_json(self, path: Path, payload: list | dict) -> None:
        with self._io_lock:
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _append_jsonl(self, path: Path, payload: dict) -> None:
        with self._io_lock:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False))
                handle.write("\n")

    def _read_jsonl(self, path: Path) -> list[dict]:
        with self._io_lock:
            if not path.exists():
                return []
            items: list[dict] = []
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    items.append(json.loads(line))
            return items

    def _write_model(self, path: Path, model: object) -> None:
        with self._io_lock:
            if hasattr(model, "model_dump_json"):
                path.write_text(model.model_dump_json(indent=2), encoding="utf-8")  # type: ignore[attr-defined]
            else:
                raise TypeError("Unsupported model type")

    def _read_model_json(self, path: Path, model_type: type[T]) -> T:
        last_error: Exception | None = None
        for _ in range(5):
            try:
                with self._io_lock:
                    return model_type.model_validate_json(path.read_text(encoding="utf-8"))  # type: ignore[attr-defined]
            except ValueError as exc:
                last_error = exc
                time.sleep(0.02)
        raise last_error or RuntimeError(f"Unable to read model json: {path}")

    def _slugify(self, value: str) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
        return cleaned or "session"
