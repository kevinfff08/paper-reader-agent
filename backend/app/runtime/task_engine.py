"""Background specialized-agent task engine with persisted events and stop support."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from backend.app.core.models.domain import (
    CompactSummary,
    MemoryNote,
    TaskAgentKind,
    TaskEvent,
    TaskSummary,
    VerificationNote,
    WorkingStateSnapshot,
)
from backend.app.llm.client import LLMClient
from backend.app.logging.session_logger import get_app_logger
from backend.app.services.verification.verifier import AnswerVerifier
from backend.app.storage.session_store import SessionStore


logger = get_app_logger("task_engine")
TERMINAL_TASK_STATES = {"completed", "failed", "cancelled"}


class TaskEngine:
    """Run specialized agents as persisted background tasks."""

    def __init__(self, *, store: SessionStore, llm_client: LLMClient, verifier: AnswerVerifier):
        self.store = store
        self.llm_client = llm_client
        self.verifier = verifier
        self._stop_flags: dict[str, threading.Event] = {}

    def start_task(
        self,
        session_id: str,
        *,
        agent_kind: TaskAgentKind,
        input_text: str = "",
        parent_run_id: str | None = None,
        snapshot: WorkingStateSnapshot | None = None,
    ) -> TaskSummary:
        task = self._create_task(
            session_id,
            agent_kind=agent_kind,
            input_text=input_text,
            parent_run_id=parent_run_id,
            snapshot=snapshot,
        )
        stop_event = threading.Event()
        self._stop_flags[task.task_id] = stop_event
        worker = threading.Thread(
            target=self._execute_task,
            args=(session_id, task.task_id),
            daemon=True,
            name=f"paperreader-task-{task.task_id}",
        )
        worker.start()
        return task

    def wait_for_task(self, session_id: str, task_id: str, *, timeout_seconds: float = 30.0) -> TaskSummary:
        deadline = datetime.now().timestamp() + timeout_seconds
        while datetime.now().timestamp() < deadline:
            task = self.store.get_task(session_id, task_id)
            if task.status in TERMINAL_TASK_STATES:
                return task
            time.sleep(0.05)
        return self.store.get_task(session_id, task_id)

    async def stream_events(self, session_id: str, task_id: str):
        sent = 0
        while True:
            events = self.store.list_task_events(session_id, task_id)
            for event in events[sent:]:
                payload = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
                yield f"data: {payload}\n\n"
                sent += 1
            task = self.store.get_task(session_id, task_id)
            if task.status in TERMINAL_TASK_STATES and sent >= len(events):
                break
            await asyncio.sleep(0.1)

    def stop_task(self, session_id: str, task_id: str) -> TaskSummary:
        stop_event = self._stop_flags.get(task_id)
        if stop_event is not None:
            stop_event.set()
        task = self.store.get_task(session_id, task_id)
        if task.status not in TERMINAL_TASK_STATES:
            task = self._update_task(task, status="cancelled", current_step="cancelled", error_message="Stopped by user")
            self._emit(task, "task_cancelled", {"message": "Stopped by user"})
        return task

    def _create_task(
        self,
        session_id: str,
        *,
        agent_kind: TaskAgentKind,
        input_text: str,
        parent_run_id: str | None,
        snapshot: WorkingStateSnapshot | None,
    ) -> TaskSummary:
        now = datetime.now(UTC)
        task = TaskSummary(
            task_id=uuid4().hex[:12],
            session_id=session_id,
            agent_kind=agent_kind,
            status="pending",
            parent_run_id=parent_run_id,
            input_text=input_text,
            snapshot_version=snapshot.version if snapshot else None,
            created_at=now,
            updated_at=now,
        )
        self.store.create_task(task)
        if snapshot is not None:
            self.store.save_working_snapshot(session_id, snapshot)
            task = self._update_task(task, result_payload={"snapshot_id": snapshot.snapshot_id})
        return task

    def _execute_task(self, session_id: str, task_id: str) -> None:
        task = self.store.get_task(session_id, task_id)
        stop_event = self._stop_flags.setdefault(task_id, threading.Event())
        task = self._update_task(task, status="running", current_step="starting", progress=5)
        self._emit(task, "task_started", {"agent_kind": task.agent_kind})
        try:
            result = self._run_specialized_agent(task, stop_event)
            if stop_event.is_set():
                task = self._update_task(task, status="cancelled", current_step="cancelled", progress=task.progress)
                self._emit(task, "task_cancelled", {"message": "Stopped by user"})
                return
            task = self._update_task(
                task,
                status="completed",
                current_step="completed",
                progress=100,
                output_preview=result.get("output_preview"),
                result_payload={**task.result_payload, **result},
            )
            self._emit(task, "task_output", {"output_preview": task.output_preview, "result_payload": task.result_payload})
            self._emit(task, "task_completed", {"status": task.status})
        except Exception as exc:  # pragma: no cover
            logger.exception("Task %s failed", task_id)
            task = self._update_task(task, status="failed", current_step="failed", error_message=str(exc))
            self._emit(task, "task_failed", {"error": str(exc)})
        finally:
            self._stop_flags.pop(task_id, None)

    def _run_specialized_agent(self, task: TaskSummary, stop_event: threading.Event) -> dict[str, Any]:
        snapshot = self._load_snapshot_for_task(task)
        if task.agent_kind == "compact":
            return self._run_compact_agent(task, snapshot, stop_event)
        if task.agent_kind == "session_memory_update":
            return self._run_session_memory_update_agent(task, snapshot, stop_event)
        if task.agent_kind == "memory_extraction":
            return self._run_memory_extraction_agent(task, snapshot, stop_event)
        return self._run_verification_agent(task, snapshot, stop_event)

    def _run_compact_agent(
        self,
        task: TaskSummary,
        snapshot: WorkingStateSnapshot,
        stop_event: threading.Event,
    ) -> dict[str, Any]:
        task = self._progress(task, 25, "freezing_boundary", "Compaction boundary created")
        if stop_event.is_set():
            return {}
        boundary_id = uuid4().hex[:12]
        evidence_lines = [f"- {ref.label}: {ref.locator or ref.page_label or 'local'}" for ref in snapshot.recent_evidence_refs[:5]]
        preserved_tail_anchor = snapshot.preserved_tail[-1] if snapshot.preserved_tail else snapshot.active_question or "tail"
        base_summary = (
            f"Active question: {snapshot.active_question or 'N/A'}\n"
            f"Unresolved items: {', '.join(snapshot.unresolved_items) or 'None'}\n"
            f"Recent evidence:\n{chr(10).join(evidence_lines) or '- None'}\n"
            f"Recent files:\n{chr(10).join(f'- {path}' for path in snapshot.recent_file_paths[:5]) or '- None'}"
        )
        content = base_summary
        if self.llm_client.is_configured:
            prompt = (
                "CRITICAL: Respond with TEXT ONLY. Do not call tools.\n\n"
                "You are the compact agent for a paper-reading runtime. Produce a compact summary that preserves"
                " active question, unresolved items, recent evidence anchors, and recent file context.\n\n"
                f"Snapshot:\n{base_summary}"
            )
            try:
                content = self.llm_client.generate(
                    prompt,
                    system="You are a compaction specialist. Preserve continuity and do not invent missing evidence.",
                    max_tokens=900,
                )
            except Exception:
                logger.info("Compact agent fell back to heuristic summary", exc_info=True)
        task = self._progress(task, 75, "ready_for_merge", "Compaction candidate ready")
        return {
            "output_preview": content[:240],
            "boundary_id": boundary_id,
            "snapshot_id": snapshot.snapshot_id,
            "candidate_summary": content,
            "preserved_tail_anchor": preserved_tail_anchor,
            "restored_context_refs": [ref.label for ref in snapshot.recent_evidence_refs[:5]],
            "merge_status": "candidate",
        }

    def _run_session_memory_update_agent(
        self,
        task: TaskSummary,
        snapshot: WorkingStateSnapshot,
        stop_event: threading.Event,
    ) -> dict[str, Any]:
        task = self._progress(task, 25, "loading_working_memory", "Loading session working memory")
        if stop_event.is_set():
            return {}
        existing = self.store.load_memory(task.session_id)
        note = existing or MemoryNote(session_id=task.session_id, path="", updated_at=datetime.now(UTC))
        if snapshot.active_question:
            note.tracked_questions = [*note.tracked_questions, snapshot.active_question][-20:]
        note.unresolved_points = list(dict.fromkeys([*note.unresolved_points, *snapshot.unresolved_items]))[-20:]
        if snapshot.active_question:
            note.confirmed_points = [*note.confirmed_points, f"Tracked from run: {snapshot.active_question}"][-20:]
        note.updated_at = datetime.now(UTC)
        self.store.save_memory(task.session_id, note)
        self._progress(task, 90, "memory_written", "Session working memory updated")
        return {"output_preview": f"Updated working memory for {snapshot.active_question or 'session'}"}

    def _run_memory_extraction_agent(
        self,
        task: TaskSummary,
        snapshot: WorkingStateSnapshot,
        stop_event: threading.Event,
    ) -> dict[str, Any]:
        task = self._progress(task, 30, "extracting", "Extracting durable session memory")
        if stop_event.is_set():
            return {}
        if snapshot.active_question:
            from backend.app.core.models.domain import LibraryCard

            self.store.save_library_card(
                LibraryCard(
                    card_id=uuid4().hex[:12],
                    session_id=task.session_id,
                    card_type="concept",
                    title=f"Question memory: {snapshot.active_question[:80]}",
                    content="\n".join(snapshot.unresolved_items or [snapshot.active_question]),
                    linked_asset_ids=[ref.asset_id for ref in snapshot.recent_evidence_refs[:4]],
                    created_at=datetime.now(UTC),
                )
            )
        self._progress(task, 90, "extracted", "Library memory updated")
        return {"output_preview": f"Extracted library memory from snapshot {snapshot.snapshot_id}"}

    def _run_verification_agent(
        self,
        task: TaskSummary,
        snapshot: WorkingStateSnapshot,
        stop_event: threading.Event,
    ) -> dict[str, Any]:
        task = self._progress(task, 20, "checking_evidence", "Checking evidence coverage")
        if stop_event.is_set():
            return {}
        evidence_refs = snapshot.recent_evidence_refs
        has_paper_evidence = any(ref.source_type == "paper" for ref in evidence_refs)
        status = "passed" if has_paper_evidence and evidence_refs else "failed"
        rationale = (
            "Verification passed because uploaded-paper evidence with locators is available."
            if status == "passed"
            else "Verification failed because uploaded-paper evidence is missing or insufficient."
        )
        note = VerificationNote(
            verification_id=uuid4().hex[:12],
            session_id=task.session_id,
            run_id=task.parent_run_id,
            question_text=snapshot.active_question or task.input_text,
            status=status,  # type: ignore[arg-type]
            rationale=rationale,
            evidence_labels=[ref.label for ref in evidence_refs[:6]],
            created_at=datetime.now(UTC),
        )
        self.store.save_verification_note(task.session_id, note)
        self._progress(task, 95, "verified", rationale)
        return {"output_preview": rationale, "verification_status": status, "verification_rationale": rationale}

    def _load_snapshot_for_task(self, task: TaskSummary) -> WorkingStateSnapshot:
        snapshot_id = task.result_payload.get("snapshot_id")
        if isinstance(snapshot_id, str):
            return self.store.get_working_snapshot(task.session_id, snapshot_id)
        now = datetime.now(UTC)
        return WorkingStateSnapshot(
            snapshot_id=uuid4().hex[:12],
            session_id=task.session_id,
            run_id=task.parent_run_id,
            version=task.snapshot_version or self.store.load_working_state_version(task.session_id),
            transcript_cursor=len(self.store.list_run_events(task.session_id, task.parent_run_id)) if task.parent_run_id else 0,
            active_question=task.input_text or None,
            created_at=now,
        )

    def _progress(self, task: TaskSummary, progress: int, step: str, message: str) -> TaskSummary:
        updated = self._update_task(task, progress=progress, current_step=step)
        self._emit(updated, "task_progress", {"progress": progress, "current_step": step})
        self._emit(updated, "task_log", {"message": message})
        return updated

    def _update_task(self, task: TaskSummary, **changes: Any) -> TaskSummary:
        updated = task.model_copy(update={"updated_at": datetime.now(UTC), **changes})
        self.store.update_task(task.session_id, updated)
        return updated

    def _emit(self, task: TaskSummary, event_type: str, payload: dict[str, Any]) -> None:
        sequence_number = len(self.store.list_task_events(task.session_id, task.task_id)) + 1
        self.store.append_task_event(
            task.session_id,
            TaskEvent(
                event_id=uuid4().hex[:12],
                task_id=task.task_id,
                sequence_number=sequence_number,
                event_type=event_type,  # type: ignore[arg-type]
                payload=payload,
                created_at=datetime.now(UTC),
            ),
        )
