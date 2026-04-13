"""Run engine with persisted events and SSE-friendly execution."""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from backend.app.core.models.domain import (
    AnalysisArtifact,
    AnalysisSection,
    ArchiveArtifact,
    CompactSummary,
    EvidenceLedgerEntry,
    EvidenceRef,
    LibraryCard,
    MemoryNote,
    ParsedDocument,
    QARecord,
    ReferenceAsset,
    RunEvent,
    RunMode,
    RunSummary,
    SessionSummary,
    TaskSummary,
    VerificationNote,
    WorkingStateSnapshot,
)
from backend.app.llm.client import LLMClient
from backend.app.logging.session_logger import get_app_logger
from backend.app.runtime.task_engine import TaskEngine
from backend.app.services.discovery.external_retrieval import ExternalRetriever
from backend.app.services.parsing.document_parser import DocumentParser
from backend.app.services.reporting.archive_report import ArchiveReportBuilder
from backend.app.services.retrieval.local_evidence import LocalEvidenceRetriever
from backend.app.services.verification.verifier import AnswerVerifier
from backend.app.storage.session_store import SessionStore


logger = get_app_logger("run_engine")
TERMINAL_RUN_STATES = {"completed", "failed"}


class RunEngine:
    """Execute session work as persisted runs with replayable events."""

    def __init__(
        self,
        *,
        store: SessionStore,
        parser: DocumentParser,
        llm_client: LLMClient,
        local_retriever: LocalEvidenceRetriever,
        external_retriever: ExternalRetriever,
        verifier: AnswerVerifier,
        archive_builder: ArchiveReportBuilder,
        task_engine: TaskEngine | None = None,
    ):
        self.store = store
        self.parser = parser
        self.llm_client = llm_client
        self.local_retriever = local_retriever
        self.external_retriever = external_retriever
        self.verifier = verifier
        self.archive_builder = archive_builder
        self.task_engine = task_engine

    def start_run(
        self,
        session_id: str,
        *,
        mode: RunMode,
        input_text: str,
        preferred_paper_ids: list[str] | None = None,
    ) -> RunSummary:
        run = self._create_run(session_id, mode=mode, input_text=input_text, preferred_paper_ids=preferred_paper_ids)
        worker = threading.Thread(
            target=self._execute_run,
            args=(session_id, run.run_id),
            daemon=True,
            name=f"paperreader-run-{run.run_id}",
        )
        worker.start()
        return run

    def run_sync(
        self,
        session_id: str,
        *,
        mode: RunMode,
        input_text: str,
        preferred_paper_ids: list[str] | None = None,
    ) -> RunSummary:
        run = self._create_run(session_id, mode=mode, input_text=input_text, preferred_paper_ids=preferred_paper_ids)
        self._execute_run(session_id, run.run_id)
        return self.store.get_run(session_id, run.run_id)

    async def stream_events(self, session_id: str, run_id: str):
        """Yield SSE frames for a run, replaying stored events first."""
        sent = 0
        while True:
            events = self.store.list_run_events(session_id, run_id)
            for event in events[sent:]:
                payload = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
                yield f"data: {payload}\n\n"
                sent += 1
            run = self.store.get_run(session_id, run_id)
            if run.status in TERMINAL_RUN_STATES and sent >= len(events):
                break
            await asyncio.sleep(0.1)

    def _create_run(
        self,
        session_id: str,
        *,
        mode: RunMode,
        input_text: str,
        preferred_paper_ids: list[str] | None = None,
    ) -> RunSummary:
        now = datetime.now(UTC)
        working_state_version = self.store.bump_working_state_version(session_id)
        run = RunSummary(
            run_id=uuid4().hex[:12],
            session_id=session_id,
            mode=mode,
            status="pending",
            input_text=input_text,
            preferred_paper_ids=preferred_paper_ids or [],
            working_state_version=working_state_version,
            verification_state="not_requested",
            created_at=now,
            updated_at=now,
        )
        self.store.create_run(run)
        return run

    def _execute_run(self, session_id: str, run_id: str) -> None:
        run = self.store.get_run(session_id, run_id)
        sequence_number = len(self.store.list_run_events(session_id, run_id))
        run = self._update_run(run, status="running")
        sequence_number = self._emit(
            run,
            sequence_number,
            "run_started",
            {"mode": run.mode, "input": run.input_text, "risk_level": run.risk_level},
        )
        try:
            if run.mode == "analyze":
                final_ref, sequence_number = self._execute_analyze(run, sequence_number)
            elif run.mode == "answer":
                final_ref, sequence_number = self._execute_answer(run, sequence_number)
            else:
                final_ref, sequence_number = self._execute_archive(run, sequence_number)
            run = self._update_run(run, status="completed", final_artifact_ref=final_ref)
            self._emit(run, sequence_number, "run_completed", {"final_artifact_ref": final_ref, "status": run.status})
        except Exception as exc:  # pragma: no cover
            logger.exception("Run %s failed", run_id)
            run = self._update_run(run, status="failed", error_message=str(exc))
            self._emit(run, sequence_number, "run_failed", {"error": str(exc), "status": run.status})

    def _execute_analyze(self, run: RunSummary, sequence_number: int) -> tuple[str, int]:
        session = self.store.get_session(run.session_id)
        docs, sequence_number = self._parse_all_papers(run, sequence_number)
        analyses = [self._analyze_paper(session, doc, run.input_text or None) for doc in docs]
        synthesis = self._build_cross_paper_synthesis(session, docs, analyses, run.input_text or None)
        self.store.save_analysis(run.session_id, synthesis)
        self._update_memory_from_analysis(session, docs, synthesis)
        self._append_compact_summary(run.session_id, f"analyze:{synthesis.analysis_id}", synthesis.sections[0].content)
        self._save_library_cards_for_analysis(run.session_id, docs, synthesis)
        summary_text = "\n\n".join(section.content for section in synthesis.sections[:2])
        sequence_number = self._emit_text(run, sequence_number, summary_text)
        sequence_number = self._emit(run, sequence_number, "memory_updated", {"layer": "working_memory"})
        if self.task_engine is not None:
            snapshot = self._build_working_snapshot(
                session,
                run,
                active_question=run.input_text or "Initial analysis",
                unresolved_items=[],
                evidence=[],
                preserved_tail=[section.content[:160] for section in synthesis.sections[:2]],
            )
            memory_task = self.task_engine.start_task(
                run.session_id,
                agent_kind="session_memory_update",
                input_text=run.input_text or "Initial analysis",
                parent_run_id=run.run_id,
                snapshot=snapshot,
            )
            extraction_task = self.task_engine.start_task(
                run.session_id,
                agent_kind="memory_extraction",
                input_text=run.input_text or "Initial analysis",
                parent_run_id=run.run_id,
                snapshot=snapshot,
            )
            run = self._attach_task_to_run(run, memory_task.task_id, extraction_task.task_id)
        return f"analysis:{synthesis.analysis_id}", sequence_number

    def _execute_answer(self, run: RunSummary, sequence_number: int) -> tuple[str, int]:
        session = self.store.get_session(run.session_id)
        question = run.input_text.strip()
        risk_level = self._classify_risk(question)
        verification_state = "pending" if risk_level == "high" else "not_requested"
        run = self._update_run(run, risk_level=risk_level, verification_state=verification_state)
        parsed_docs = self.store.load_parsed_documents(run.session_id)
        if not parsed_docs and self.store.list_papers(run.session_id):
            parsed_docs, sequence_number = self._parse_all_papers(run, sequence_number)
        if run.preferred_paper_ids:
            parsed_docs = [doc for doc in parsed_docs if doc.paper_id in run.preferred_paper_ids]
        analyses = self.store.list_analyses(run.session_id)
        qa_records = self.store.list_qa_records(run.session_id)
        references = self.store.list_references(run.session_id)

        state: dict[str, object] = {
            "local_evidence": [],
            "paper_evidence": [],
            "analysis_evidence": [],
            "reference_evidence": [],
            "localized_refs": [],
            "external_used": False,
            "memory_updated": False,
        }

        sequence_number = self._emit(run, sequence_number, "verification_required", {"risk_level": risk_level})
        compact_task: TaskSummary | None = None
        compact_merged = False
        if self.task_engine is not None:
            compact_snapshot = self._build_working_snapshot(
                session,
                run,
                active_question=question,
                unresolved_items=[question],
                evidence=[],
                preserved_tail=["question_received", question],
            )
            compact_task = self.task_engine.start_task(
                run.session_id,
                agent_kind="compact",
                input_text=question,
                parent_run_id=run.run_id,
                snapshot=compact_snapshot,
            )
            run = self._attach_task_to_run(run, compact_task.task_id)

        for _ in range(6):
            action = self._decide_next_action(
                question=question,
                risk_level=risk_level,
                parsed_docs=parsed_docs,
                analyses=analyses,
                references=references,
                state=state,
            )
            if action == "finish":
                if risk_level == "high" and not state["paper_evidence"]:
                    sequence_number = self._emit(
                        run,
                        sequence_number,
                        "verification_required",
                        {"reason": "High-risk question requires uploaded-paper evidence before completion."},
                    )
                    action = "read_paper_segments"
                else:
                    break

            sequence_number = self._emit(run, sequence_number, "tool_call_started", {"tool": action})
            if action == "search_local_evidence":
                evidence = self.local_retriever.retrieve(
                    question,
                    parsed_docs=parsed_docs,
                    analyses=analyses,
                    qa_records=qa_records,
                    references=references,
                )
                sequence_number = self._merge_evidence(run, sequence_number, state, "local_evidence", evidence)
            elif action == "read_paper_segments":
                evidence = self.local_retriever.retrieve(
                    question,
                    parsed_docs=parsed_docs,
                    analyses=[],
                    qa_records=[],
                    references=[],
                    limit=4,
                )
                evidence = [item for item in evidence if item.source_type == "paper"]
                sequence_number = self._merge_evidence(run, sequence_number, state, "paper_evidence", evidence)
            elif action == "read_analysis_notes":
                evidence = self.local_retriever.retrieve(
                    question,
                    parsed_docs=[],
                    analyses=analyses,
                    qa_records=[],
                    references=[],
                    limit=4,
                )
                evidence = [item for item in evidence if item.source_type == "analysis"]
                sequence_number = self._merge_evidence(run, sequence_number, state, "analysis_evidence", evidence)
            elif action == "read_reference_asset":
                evidence = self.local_retriever.retrieve(
                    question,
                    parsed_docs=[],
                    analyses=[],
                    qa_records=[],
                    references=references,
                    limit=4,
                )
                evidence = [item for item in evidence if item.source_type == "reference"]
                sequence_number = self._merge_evidence(run, sequence_number, state, "reference_evidence", evidence)
            elif action == "search_external_sources":
                localized_refs: list[ReferenceAsset] = state["localized_refs"]  # type: ignore[assignment]
                for item in self.external_retriever.search(question, limit=2):
                    reference = self._localize_reference(run.session_id, item.title, item.source_kind, item.source_url, item.summary)
                    localized_refs.append(reference)
                    self.store.save_reference(run.session_id, reference)
                references = self.store.list_references(run.session_id)
            elif action == "update_session_memory":
                combined_refs: list[ReferenceAsset] = state["localized_refs"]  # type: ignore[assignment]
                combined_evidence = self._combined_evidence(state)
                self._update_memory_from_question(session, question, combined_refs, combined_evidence)
                self._append_compact_summary(run.session_id, f"qa:{question[:40]}", f"Question: {question}\nEvidence count: {len(combined_evidence)}")
                state["memory_updated"] = True
                sequence_number = self._emit(run, sequence_number, "memory_updated", {"layer": "working_memory"})
            if action == "search_external_sources":
                state["external_used"] = True
            sequence_number = self._emit(run, sequence_number, "tool_call_finished", {"tool": action})
            if compact_task is not None and not compact_merged:
                compact_merged, sequence_number = self._maybe_merge_compact_candidate(
                    run,
                    compact_task.task_id,
                    compact_merged,
                    sequence_number,
                )

        combined_evidence = self._combined_evidence(state)
        localized_refs: list[ReferenceAsset] = state["localized_refs"]  # type: ignore[assignment]
        if risk_level == "high" and not any(item.source_type == "paper" for item in combined_evidence):
            raise RuntimeError("Unable to satisfy high-risk evidence gate with uploaded-paper evidence")

        answer_text = self._draft_answer(question, combined_evidence, localized_refs)
        if risk_level == "high" and self.task_engine is not None:
            verification_snapshot = self._build_working_snapshot(
                session,
                run,
                active_question=question,
                unresolved_items=[],
                evidence=combined_evidence,
                preserved_tail=[question, answer_text[:240]],
            )
            verification_task = self.task_engine.start_task(
                run.session_id,
                agent_kind="verification",
                input_text=question,
                parent_run_id=run.run_id,
                snapshot=verification_snapshot,
            )
            run = self._attach_task_to_run(run, verification_task.task_id)
            verified = self.task_engine.wait_for_task(run.session_id, verification_task.task_id, timeout_seconds=10.0)
            verification_result = str(verified.result_payload.get("verification_status", "failed"))
            if verified.status != "completed" or verification_result != "passed":
                run = self._update_run(run, verification_state="failed")
                sequence_number = self._emit(
                    run,
                    sequence_number,
                    "verification_required",
                    {"reason": verified.result_payload.get("verification_rationale", "Verification task failed")},
                )
                raise RuntimeError("High-risk verification did not pass")
            run = self._update_run(run, verification_state="passed")

        sequence_number = self._emit_text(run, sequence_number, answer_text)
        verification_status = self.verifier.verify(
            evidence_refs=combined_evidence,
            used_external_sources=bool(localized_refs),
        )
        qa_record = QARecord(
            question_id=uuid4().hex[:12],
            question_text=question,
            answer_text=answer_text,
            evidence_refs=combined_evidence,
            retrieval_refs=localized_refs,
            verification_status=verification_status,
            created_at=datetime.now(UTC),
        )
        self.store.save_qa_record(run.session_id, qa_record)
        if not state["memory_updated"]:
            self._update_memory_from_question(session, question, localized_refs, combined_evidence)
            self._append_compact_summary(run.session_id, f"qa:{qa_record.question_id}", answer_text[:1200])
            sequence_number = self._emit(run, sequence_number, "memory_updated", {"layer": "working_memory"})
        if self.task_engine is not None:
            post_snapshot = self._build_working_snapshot(
                session,
                run,
                active_question=question,
                unresolved_items=[],
                evidence=combined_evidence,
                preserved_tail=[question, answer_text[:240]],
            )
            memory_task = self.task_engine.start_task(
                run.session_id,
                agent_kind="session_memory_update",
                input_text=question,
                parent_run_id=run.run_id,
                snapshot=post_snapshot,
            )
            extraction_task = self.task_engine.start_task(
                run.session_id,
                agent_kind="memory_extraction",
                input_text=question,
                parent_run_id=run.run_id,
                snapshot=post_snapshot,
            )
            run = self._attach_task_to_run(run, memory_task.task_id, extraction_task.task_id)
        return f"qa:{qa_record.question_id}", sequence_number

    def _execute_archive(self, run: RunSummary, sequence_number: int) -> tuple[str, int]:
        artifacts = self.store.get_artifacts(run.session_id)
        sequence_number = self._emit(run, sequence_number, "tool_call_started", {"tool": "build_archive_draft"})
        markdown = self.archive_builder.build(
            session=self.store.get_session(run.session_id),
            analyses=artifacts.analyses,
            qa_records=artifacts.qa_records,
            references=artifacts.references,
            memory_note=artifacts.memory,
            compact_summaries=artifacts.compact_summaries,
            library_cards=artifacts.library_cards,
        )
        archive = ArchiveArtifact(
            archive_id=uuid4().hex[:12],
            session_id=run.session_id,
            markdown_path="",
            created_at=datetime.now(UTC),
        )
        archive = self.store.save_archive(run.session_id, archive, markdown)
        sequence_number = self._emit(run, sequence_number, "tool_call_finished", {"tool": "build_archive_draft"})
        sequence_number = self._emit_text(run, sequence_number, "Archive draft generated and saved to the session.")
        return f"archive:{archive.archive_id}", sequence_number

    def _parse_all_papers(self, run: RunSummary, sequence_number: int) -> tuple[list[ParsedDocument], int]:
        session = self.store.get_session(run.session_id)
        docs: list[ParsedDocument] = []
        for paper in self.store.list_papers(run.session_id):
            sequence_number = self._emit(
                run,
                sequence_number,
                "tool_call_started",
                {"tool": "parse/index", "paper_id": paper.paper_id, "filename": paper.filename},
            )
            parsed = self.parser.parse(paper.paper_id, Path(paper.original_path))
            self.store.save_parsed_document(run.session_id, parsed)
            docs.append(parsed)
            sequence_number = self._emit(
                run,
                sequence_number,
                "tool_call_finished",
                {"tool": "parse/index", "paper_id": paper.paper_id, "title": parsed.title},
            )
        self._update_memory_from_parse(session, docs)
        return docs, sequence_number

    def _merge_evidence(
        self,
        run: RunSummary,
        sequence_number: int,
        state: dict[str, object],
        bucket_key: Literal["local_evidence", "paper_evidence", "analysis_evidence", "reference_evidence"],
        evidence: list[EvidenceRef],
    ) -> int:
        bucket: list[EvidenceRef] = state[bucket_key]  # type: ignore[assignment]
        existing_keys = {(item.label, item.excerpt) for item in self._combined_evidence(state)}
        for item in evidence:
            key = (item.label, item.excerpt)
            if key in existing_keys:
                continue
            bucket.append(item)
            existing_keys.add(key)
            self.store.save_evidence_entry(
                run.session_id,
                EvidenceLedgerEntry(
                    evidence_id=uuid4().hex[:12],
                    session_id=run.session_id,
                    run_id=run.run_id,
                    source_type=item.source_type,
                    asset_id=item.asset_id,
                    label=item.label,
                    excerpt=item.excerpt,
                    locator=item.locator,
                    recorded_at=datetime.now(UTC),
                ),
            )
            sequence_number = self._emit(
                run,
                sequence_number,
                "evidence_added",
                {"label": item.label, "source_type": item.source_type, "locator": item.locator},
            )
        return sequence_number

    def _combined_evidence(self, state: dict[str, object]) -> list[EvidenceRef]:
        combined: list[EvidenceRef] = []
        for key in ("paper_evidence", "analysis_evidence", "reference_evidence", "local_evidence"):
            combined.extend(state[key])  # type: ignore[arg-type]
        deduped: list[EvidenceRef] = []
        seen: set[tuple[str, str]] = set()
        for item in combined:
            key = (item.label, item.excerpt)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    def _classify_risk(self, question: str) -> Literal["low", "medium", "high"]:
        lowered = question.lower()
        high_markers = (
            "method",
            "experiment",
            "result",
            "dataset",
            "baseline",
            "ablation",
            "limitation",
            "equation",
            "figure",
            "table",
            "implementation",
            "hyperparameter",
        )
        medium_markers = ("compare", "difference", "related work", "why", "how", "assumption")
        if any(marker in lowered for marker in high_markers):
            return "high"
        if any(marker in lowered for marker in medium_markers):
            return "medium"
        return "low"

    def _decide_next_action(
        self,
        *,
        question: str,
        risk_level: str,
        parsed_docs: list[ParsedDocument],
        analyses: list[AnalysisArtifact],
        references: list[ReferenceAsset],
        state: dict[str, object],
    ) -> str:
        available_tools = [
            "search_local_evidence",
            "read_paper_segments",
            "read_analysis_notes",
            "read_reference_asset",
            "search_external_sources",
            "update_session_memory",
            "finish",
        ]
        if self.llm_client.is_configured:
            prompt = (
                f"Question: {question}\n"
                f"Risk level: {risk_level}\n"
                f"Paper count: {len(parsed_docs)}\n"
                f"Analysis count: {len(analyses)}\n"
                f"Reference count: {len(references)}\n"
                f"Current state: local={len(state['local_evidence'])}, paper={len(state['paper_evidence'])}, "
                f"analysis={len(state['analysis_evidence'])}, reference={len(state['reference_evidence'])}, "
                f"external_used={state['external_used']}, memory_updated={state['memory_updated']}\n"
                f"Available tools: {', '.join(available_tools)}\n"
                "Choose the single best next action. High-risk questions must not finish without uploaded-paper evidence. "
                "Return JSON like {\"action\": \"search_local_evidence\"}."
            )
            try:
                response = self.llm_client.generate_json(
                    prompt,
                    system="You are controlling a paper-reading runtime. Choose one tool action only.",
                    max_tokens=150,
                )
                action = response.get("action") if isinstance(response, dict) else None
                if isinstance(action, str) and action in available_tools:
                    return action
            except Exception:
                logger.info("Falling back to heuristic tool selection", exc_info=True)

        if not state["local_evidence"]:
            return "search_local_evidence"
        if risk_level == "high" and not state["paper_evidence"]:
            return "read_paper_segments"
        if analyses and not state["analysis_evidence"]:
            return "read_analysis_notes"
        if references and not state["reference_evidence"]:
            return "read_reference_asset"
        if len(self._combined_evidence(state)) < 2 and not state["external_used"]:
            return "search_external_sources"
        if not state["memory_updated"]:
            return "update_session_memory"
        return "finish"

    def _attach_task_to_run(self, run: RunSummary, *task_ids: str) -> RunSummary:
        merged_ids = list(dict.fromkeys([*run.active_background_task_ids, *task_ids]))
        return self._update_run(run, active_background_task_ids=merged_ids)

    def _build_working_snapshot(
        self,
        session: SessionSummary,
        run: RunSummary,
        *,
        active_question: str | None,
        unresolved_items: list[str],
        evidence: list[EvidenceRef],
        preserved_tail: list[str],
    ) -> WorkingStateSnapshot:
        recent_files = [item.path for item in self.store.list_session_files(session.session_id)[:8]]
        snapshot = WorkingStateSnapshot(
            snapshot_id=uuid4().hex[:12],
            session_id=session.session_id,
            run_id=run.run_id,
            version=run.working_state_version,
            transcript_cursor=len(self.store.list_run_events(session.session_id, run.run_id)),
            active_question=active_question,
            unresolved_items=unresolved_items[:8],
            active_plan=[f"Mode: {run.mode}", f"Session: {session.session_name}"],
            recent_evidence_refs=evidence[:8],
            recent_file_paths=recent_files,
            preserved_tail=preserved_tail[:8],
            created_at=datetime.now(UTC),
        )
        self.store.save_working_snapshot(session.session_id, snapshot)
        return snapshot

    def _maybe_merge_compact_candidate(
        self,
        run: RunSummary,
        task_id: str,
        already_merged: bool,
        sequence_number: int,
    ) -> tuple[bool, int]:
        if already_merged:
            return True, sequence_number
        try:
            task = self.store.get_task(run.session_id, task_id)
        except FileNotFoundError:
            return False, sequence_number
        if task.status not in {"completed", "failed", "cancelled"}:
            return False, sequence_number
        if task.status != "completed":
            return False, sequence_number
        if task.result_payload.get("merge_status") != "candidate":
            return task.result_payload.get("merge_status") == "merged", sequence_number
        if task.snapshot_version != run.working_state_version:
            updated = task.model_copy(
                update={
                    "result_payload": {**task.result_payload, "merge_status": "stale_candidate"},
                    "updated_at": datetime.now(UTC),
                }
            )
            self.store.update_task(run.session_id, updated)
            return False, sequence_number
        summary = CompactSummary(
            summary_id=uuid4().hex[:12],
            session_id=run.session_id,
            boundary_label=f"run:{run.run_id}",
            content=str(task.result_payload.get("candidate_summary", "")),
            boundary_id=str(task.result_payload.get("boundary_id", "")),
            snapshot_version=task.snapshot_version,
            preserved_tail_anchor=task.result_payload.get("preserved_tail_anchor"),
            restored_context_refs=list(task.result_payload.get("restored_context_refs", [])),
            created_at=datetime.now(UTC),
        )
        self.store.save_compact_summary(run.session_id, summary)
        updated = task.model_copy(
            update={
                "result_payload": {**task.result_payload, "merge_status": "merged"},
                "updated_at": datetime.now(UTC),
            }
        )
        self.store.update_task(run.session_id, updated)
        sequence_number = self._emit(
            run,
            sequence_number,
            "memory_updated",
            {"layer": "compact_memory", "boundary_id": summary.boundary_id, "snapshot_version": summary.snapshot_version},
        )
        return True, sequence_number

    def _update_run(self, run: RunSummary, **changes) -> RunSummary:
        updated = run.model_copy(update={"updated_at": datetime.now(UTC), **changes})
        self.store.update_run(run.session_id, updated)
        return updated

    def _emit(self, run: RunSummary, sequence_number: int, event_type: str, payload: dict) -> int:
        next_sequence = sequence_number + 1
        self.store.append_run_event(
            run.session_id,
            RunEvent(
                event_id=uuid4().hex[:12],
                run_id=run.run_id,
                sequence_number=next_sequence,
                event_type=event_type,  # type: ignore[arg-type]
                payload=payload,
                created_at=datetime.now(UTC),
            ),
        )
        return next_sequence

    def _emit_text(self, run: RunSummary, sequence_number: int, text: str) -> int:
        if not text:
            return sequence_number
        if self.llm_client.is_configured:
            prompt = f"Rewrite the following answer faithfully. Keep meaning and evidence intact.\n\n{text}"
            try:
                content = ""
                for event in self.llm_client.stream_chat(
                    [{"role": "user", "content": prompt}],
                    system="You are streaming a polished final answer for a paper-reading assistant.",
                    max_tokens=1400,
                ):
                    if event["type"] == "text_delta":
                        delta = str(event["delta"])
                        content += delta
                        sequence_number = self._emit(run, sequence_number, "assistant_delta", {"delta": delta})
                if content:
                    return sequence_number
            except Exception:
                logger.info("Falling back to local text chunking", exc_info=True)
        for chunk in self._chunk_text(text):
            sequence_number = self._emit(run, sequence_number, "assistant_delta", {"delta": chunk})
        return sequence_number

    def _chunk_text(self, text: str, chunk_size: int = 160) -> list[str]:
        chunks: list[str] = []
        remaining = text.strip()
        while remaining:
            if len(remaining) <= chunk_size:
                chunks.append(remaining)
                break
            split_at = remaining.rfind(" ", 0, chunk_size)
            if split_at <= 0:
                split_at = chunk_size
            chunks.append(remaining[:split_at])
            remaining = remaining[split_at:].lstrip()
        return chunks

    def _analyze_paper(self, session: SessionSummary, doc: ParsedDocument, focus_question: str | None) -> AnalysisArtifact:
        sections = [
            AnalysisSection(key="core_contribution", title="Core Contribution", content=self._section_text(doc, "core_contribution", focus_question)),
            AnalysisSection(key="problem_definition", title="Problem Definition", content=self._section_text(doc, "problem_definition", focus_question)),
            AnalysisSection(key="method_details", title="Method Details", content=self._section_text(doc, "method_details", focus_question)),
            AnalysisSection(key="experiments", title="Experiments and Results", content=self._section_text(doc, "experiments", focus_question)),
            AnalysisSection(key="limitations", title="Limitations", content=self._section_text(doc, "limitations", focus_question)),
            AnalysisSection(key="related_work", title="Related Work Context", content=self._section_text(doc, "related_work", focus_question)),
            AnalysisSection(key="follow_up", title="Good Follow-up Questions", content=self._section_text(doc, "follow_up", focus_question)),
        ]
        analysis_id = uuid4().hex[:12]
        session_dir = self.store.session_dir(session.session_id)
        markdown_path = session_dir / "analysis" / f"{analysis_id}.md"
        markdown_path.write_text(self._analysis_markdown(doc.title, sections), encoding="utf-8")
        artifact = AnalysisArtifact(
            analysis_id=analysis_id,
            session_id=session.session_id,
            paper_ids=[doc.paper_id],
            title=f"Single-Paper Analysis: {doc.title}",
            sections=sections,
            markdown_path=str(markdown_path),
            created_at=datetime.now(UTC),
        )
        self.store.save_analysis(session.session_id, artifact)
        return artifact

    def _build_cross_paper_synthesis(
        self,
        session: SessionSummary,
        parsed_docs: list[ParsedDocument],
        analyses: list[AnalysisArtifact],
        focus_question: str | None,
    ) -> AnalysisArtifact:
        titles = [doc.title for doc in parsed_docs]
        base_content = [
            f"The session contains {len(parsed_docs)} paper(s): {', '.join(titles)}.",
            "The synthesis first compares the stated problem definitions, then aligns methods, evidence quality, and open questions.",
        ]
        if focus_question:
            base_content.append(f"Current focus question: {focus_question}")
        synthesis_sections = [
            AnalysisSection(key="overview", title="Cross-Paper Overview", content="\n".join(base_content)),
            AnalysisSection(
                key="comparative_insights",
                title="Comparative Insights",
                content="\n\n".join(
                    f"- {analysis.title}: {analysis.sections[0].content[:250]}"
                    for analysis in analyses
                ),
            ),
            AnalysisSection(
                key="study_plan",
                title="Suggested Study Order",
                content="Start with the paper that defines the clearest problem framing, then compare method sections, and finally inspect experiments and limitations side by side.",
            ),
        ]
        analysis_id = uuid4().hex[:12]
        session_dir = self.store.session_dir(session.session_id)
        markdown_path = session_dir / "analysis" / f"{analysis_id}.md"
        markdown_path.write_text(self._analysis_markdown("Cross-Paper Synthesis", synthesis_sections), encoding="utf-8")
        return AnalysisArtifact(
            analysis_id=analysis_id,
            session_id=session.session_id,
            paper_ids=[doc.paper_id for doc in parsed_docs],
            title="Cross-Paper Synthesis",
            sections=synthesis_sections,
            markdown_path=str(markdown_path),
            created_at=datetime.now(UTC),
        )

    def _section_text(self, doc: ParsedDocument, section_key: str, focus_question: str | None) -> str:
        local_context = self._pick_section_context(doc, section_key)
        if self.llm_client.is_configured:
            prompt = (
                f"Paper title: {doc.title}\n\n"
                f"Abstract:\n{doc.abstract}\n\n"
                f"Relevant extracted content:\n{local_context}\n\n"
                f"Write the '{section_key}' section for a PhD-level paper reading assistant."
            )
            if focus_question:
                prompt += f"\n\nFocus question from user: {focus_question}"
            try:
                return self.llm_client.generate(
                    prompt,
                    system="You are a rigorous research reading assistant. Ground claims in the supplied material and avoid speculation.",
                    max_tokens=1200,
                )
            except Exception:
                pass
        return self._heuristic_section(doc, section_key, local_context, focus_question)

    def _pick_section_context(self, doc: ParsedDocument, section_key: str) -> str:
        mapping = {
            "core_contribution": ("abstract", "introduction"),
            "problem_definition": ("introduction", "background"),
            "method_details": ("method", "approach"),
            "experiments": ("experiments", "results"),
            "limitations": ("limitations", "discussion", "conclusion"),
            "related_work": ("related work", "background"),
            "follow_up": ("conclusion", "discussion", "limitations"),
        }
        wanted = mapping.get(section_key, ())
        chosen = [
            section.content
            for section in doc.sections
            if any(token in section.heading.lower() for token in wanted)
        ]
        return "\n\n".join(chosen[:3]) or doc.abstract or doc.plain_text[:4000]

    def _heuristic_section(self, doc: ParsedDocument, section_key: str, local_context: str, focus_question: str | None) -> str:
        intro = f"This section is drafted from the locally parsed source material for '{doc.title}'."
        focus_line = f" The current user focus is: {focus_question}." if focus_question else ""
        section_templates = {
            "core_contribution": "The paper appears to make its main contribution by defining a concrete research objective and proposing a corresponding technical approach.",
            "problem_definition": "The paper frames a specific problem setting and motivates why the current alternatives are insufficient.",
            "method_details": "The method section should be read carefully for model structure, assumptions, optimization details, and any implementation-sensitive choices.",
            "experiments": "The experimental section should be interpreted by checking datasets, baselines, evaluation metrics, and the extent to which results justify the paper's claims.",
            "limitations": "The limitations are partly explicit and partly implicit; pay attention to missing ablations, narrow benchmarks, and assumptions that may not generalize.",
            "related_work": "The paper should be located among nearby approaches rather than read in isolation.",
            "follow_up": "Good follow-up questions usually probe assumptions, missing experimental details, reproducibility, and connections to related papers.",
        }
        return f"{intro}{focus_line}\n\n{section_templates[section_key]}\n\nEvidence excerpt:\n{local_context[:1800]}"

    def _draft_answer(self, question: str, evidence: list[EvidenceRef], references: list[ReferenceAsset]) -> str:
        evidence_block = "\n\n".join(f"- {item.label}: {item.excerpt[:300]}" for item in evidence[:4])
        ref_block = "\n".join(f"- {item.title}: {item.summary[:200]}" for item in references)
        if self.llm_client.is_configured:
            prompt = (
                f"Question:\n{question}\n\n"
                f"Local evidence:\n{evidence_block}\n\n"
                f"New external references:\n{ref_block or 'None'}\n\n"
                "Answer the question at a PhD reading depth. Use the local evidence first and mention when new references informed the answer."
            )
            try:
                return self.llm_client.generate(
                    prompt,
                    system="You are a rigorous research reading assistant. Prefer local evidence, then explicitly integrate external references.",
                    max_tokens=1200,
                )
            except Exception:
                pass
        lines = [
            "This answer is grounded in the session-local evidence first.",
            "",
            f"Question: {question}",
            "",
            "Relevant evidence:",
            evidence_block or "- No strong local evidence found.",
        ]
        if references:
            lines.extend(["", "Additional external references were localized:", ref_block])
        return "\n".join(lines)

    def _localize_reference(self, session_id: str, title: str, source_kind: str, source_url: str, summary: str) -> ReferenceAsset:
        session_dir = self.store.session_dir(session_id)
        reference_id = uuid4().hex[:12]
        path = session_dir / "references" / f"{reference_id}.md"
        path.write_text(f"# {title}\n\nSource: {source_url}\n\n{summary}\n", encoding="utf-8")
        return ReferenceAsset(
            reference_id=reference_id,
            title=title,
            source_kind=source_kind,  # type: ignore[arg-type]
            source_url=source_url,
            localized_path=str(path),
            summary=summary,
            created_at=datetime.now(UTC),
        )

    def _update_memory_from_parse(self, session: SessionSummary, parsed_docs: list[ParsedDocument]) -> None:
        existing = self.store.load_memory(session.session_id)
        memory = existing or MemoryNote(session_id=session.session_id, path="", updated_at=datetime.now(UTC))
        memory.paper_titles = sorted({*memory.paper_titles, *[doc.title for doc in parsed_docs]})
        memory.updated_at = datetime.now(UTC)
        self.store.save_memory(session.session_id, memory)

    def _update_memory_from_analysis(self, session: SessionSummary, parsed_docs: list[ParsedDocument], synthesis: AnalysisArtifact) -> None:
        existing = self.store.load_memory(session.session_id)
        memory = existing or MemoryNote(session_id=session.session_id, path="", updated_at=datetime.now(UTC))
        memory.paper_titles = sorted({*memory.paper_titles, *[doc.title for doc in parsed_docs]})
        memory.confirmed_points = sorted({*memory.confirmed_points, "Initial analysis completed", synthesis.title})
        memory.updated_at = datetime.now(UTC)
        self.store.save_memory(session.session_id, memory)

    def _update_memory_from_question(
        self,
        session: SessionSummary,
        question: str,
        references: list[ReferenceAsset],
        evidence: list[EvidenceRef],
    ) -> None:
        existing = self.store.load_memory(session.session_id)
        memory = existing or MemoryNote(session_id=session.session_id, path="", updated_at=datetime.now(UTC))
        memory.tracked_questions = [*memory.tracked_questions, question][-20:]
        memory.reference_titles = sorted({*memory.reference_titles, *[reference.title for reference in references]})
        if evidence:
            memory.confirmed_points = [*memory.confirmed_points, f"Answered: {question}"][-20:]
        else:
            memory.unresolved_points = [*memory.unresolved_points, question][-20:]
        memory.updated_at = datetime.now(UTC)
        self.store.save_memory(session.session_id, memory)

    def _append_compact_summary(self, session_id: str, boundary_label: str, content: str) -> None:
        self.store.save_compact_summary(
            session_id,
            CompactSummary(
                summary_id=uuid4().hex[:12],
                session_id=session_id,
                boundary_label=boundary_label,
                content=content,
                boundary_id=uuid4().hex[:12],
                snapshot_version=self.store.load_working_state_version(session_id),
                preserved_tail_anchor=boundary_label,
                created_at=datetime.now(UTC),
            ),
        )

    def _save_library_cards_for_analysis(
        self,
        session_id: str,
        docs: list[ParsedDocument],
        synthesis: AnalysisArtifact,
    ) -> None:
        for doc in docs:
            self.store.save_library_card(
                LibraryCard(
                    card_id=uuid4().hex[:12],
                    session_id=session_id,
                    card_type="paper",
                    title=doc.title,
                    content=(doc.abstract or doc.plain_text[:600]).strip(),
                    linked_asset_ids=[doc.paper_id],
                    created_at=datetime.now(UTC),
                ),
            )
        self.store.save_library_card(
            LibraryCard(
                card_id=uuid4().hex[:12],
                session_id=session_id,
                card_type="session",
                title=f"Session synthesis for {self.store.get_session(session_id).session_name}",
                content="\n\n".join(section.content for section in synthesis.sections[:2]),
                linked_asset_ids=synthesis.paper_ids,
                created_at=datetime.now(UTC),
            ),
        )

    def _analysis_markdown(self, title: str, sections: list[AnalysisSection]) -> str:
        lines = [f"# {title}", ""]
        for section in sections:
            lines.append(f"## {section.title}")
            lines.append(section.content)
            lines.append("")
        return "\n".join(lines).strip() + "\n"
