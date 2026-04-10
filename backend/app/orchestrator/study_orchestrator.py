"""Session analysis, QA, verification, and archive orchestration."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from backend.app.llm.client import LLMClient
from backend.app.logging.session_logger import get_session_logger
from backend.app.models.domain import (
    AnalysisArtifact,
    AnalysisSection,
    ArchiveArtifact,
    MemoryNote,
    ParsedDocument,
    QARecord,
    ReferenceAsset,
    SessionSummary,
    TaskStatus,
)
from backend.app.parsers.document_parser import DocumentParser
from backend.app.reports.archive_report import ArchiveReportBuilder
from backend.app.retrieval.external_retrieval import ExternalRetriever
from backend.app.retrieval.local_retrieval import LocalEvidenceRetriever
from backend.app.storage.session_store import SessionStore
from backend.app.verification.verifier import AnswerVerifier


class StudyOrchestrator:
    """Run the staged single-orchestrator workflow for a session."""

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
    ):
        self.store = store
        self.parser = parser
        self.llm_client = llm_client
        self.local_retriever = local_retriever
        self.external_retriever = external_retriever
        self.verifier = verifier
        self.archive_builder = archive_builder

    def analyze_session(self, session_id: str, focus_question: str | None = None) -> AnalysisArtifact:
        session = self.store.get_session(session_id)
        logger = self._session_logger(session)
        parsed_docs = self._parse_all_papers(session)
        self._append_task(session, "plan", "running", "Generating study outline")
        analyses = [self._analyze_paper(session, doc, focus_question) for doc in parsed_docs]
        synthesis = self._build_cross_paper_synthesis(session, parsed_docs, analyses, focus_question)
        self.store.save_analysis(session.session_id, synthesis)
        self._update_memory_from_analysis(session, parsed_docs, synthesis)
        logger.info("Analysis complete for %d papers", len(parsed_docs))
        self._append_task(session, "analyze", "completed", "Analysis completed")
        return synthesis

    def answer_question(
        self,
        session_id: str,
        question: str,
        preferred_paper_ids: list[str] | None = None,
    ) -> QARecord:
        session = self.store.get_session(session_id)
        self._append_task(session, "answer", "running", "Answering follow-up question")
        parsed_docs = self.store.load_parsed_documents(session_id)
        analyses = self.store.list_analyses(session_id)
        qa_records = self.store.list_qa_records(session_id)
        references = self.store.list_references(session_id)
        if preferred_paper_ids:
            parsed_docs = [doc for doc in parsed_docs if doc.paper_id in preferred_paper_ids]

        local_evidence = self.local_retriever.retrieve(
            question,
            parsed_docs=parsed_docs,
            analyses=analyses,
            qa_records=qa_records,
            references=references,
        )

        localized_refs: list[ReferenceAsset] = []
        if len(local_evidence) < 2:
            self._append_task(session, "verify", "running", "Fetching supplemental external references")
            for item in self.external_retriever.search(question, limit=2):
                reference = self._localize_reference(session_id, item.title, item.source_kind, item.source_url, item.summary)
                localized_refs.append(reference)
                self.store.save_reference(session_id, reference)
            references = self.store.list_references(session_id)
            local_evidence = self.local_retriever.retrieve(
                question,
                parsed_docs=parsed_docs,
                analyses=analyses,
                qa_records=qa_records,
                references=references,
            )

        answer_text = self._draft_answer(question, local_evidence, localized_refs)
        verification_status = self.verifier.verify(
            evidence_refs=local_evidence,
            used_external_sources=bool(localized_refs),
        )
        qa_record = QARecord(
            question_id=uuid4().hex[:12],
            question_text=question,
            answer_text=answer_text,
            evidence_refs=local_evidence,
            retrieval_refs=localized_refs,
            verification_status=verification_status,
            created_at=datetime.now(UTC),
        )
        self.store.save_qa_record(session_id, qa_record)
        self._update_memory_from_question(session, question, localized_refs)
        self._append_task(session, "answer", "completed", "Question answered")
        return qa_record

    def build_archive(self, session_id: str) -> ArchiveArtifact:
        session = self.store.get_session(session_id)
        self._append_task(session, "archive", "running", "Building Markdown archive")
        artifacts = self.store.get_artifacts(session_id)
        markdown = self.archive_builder.build(
            session=session,
            analyses=artifacts.analyses,
            qa_records=artifacts.qa_records,
            references=artifacts.references,
            memory_note=artifacts.memory,
        )
        archive = ArchiveArtifact(
            archive_id=uuid4().hex[:12],
            session_id=session_id,
            markdown_path="",
            created_at=datetime.now(UTC),
        )
        archive = self.store.save_archive(session_id, archive, markdown)
        self._append_task(session, "archive", "completed", "Archive generated")
        return archive

    def _parse_all_papers(self, session: SessionSummary) -> list[ParsedDocument]:
        self._append_task(session, "parse", "running", "Parsing uploaded papers")
        parsed_docs: list[ParsedDocument] = []
        for paper in self.store.list_papers(session.session_id):
            parsed = self.parser.parse(paper.paper_id, Path(paper.original_path))
            self.store.save_parsed_document(session.session_id, parsed)
            parsed_docs.append(parsed)
        self._append_task(session, "parse", "completed", "Paper parsing completed")
        return parsed_docs

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

    def _draft_answer(self, question: str, evidence: list, references: list[ReferenceAsset]) -> str:
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

    def _update_memory_from_analysis(self, session: SessionSummary, parsed_docs: list[ParsedDocument], synthesis: AnalysisArtifact) -> None:
        existing = self.store.load_memory(session.session_id)
        memory = existing or MemoryNote(session_id=session.session_id, path="", updated_at=datetime.now(UTC))
        memory.paper_titles = sorted({*memory.paper_titles, *[doc.title for doc in parsed_docs]})
        memory.confirmed_points = sorted({*memory.confirmed_points, "Initial analysis completed", synthesis.title})
        memory.updated_at = datetime.now(UTC)
        self.store.save_memory(session.session_id, memory)

    def _update_memory_from_question(self, session: SessionSummary, question: str, references: list[ReferenceAsset]) -> None:
        existing = self.store.load_memory(session.session_id)
        memory = existing or MemoryNote(session_id=session.session_id, path="", updated_at=datetime.now(UTC))
        memory.tracked_questions = [*memory.tracked_questions, question][-20:]
        memory.reference_titles = sorted({*memory.reference_titles, *[reference.title for reference in references]})
        memory.updated_at = datetime.now(UTC)
        self.store.save_memory(session.session_id, memory)

    def _append_task(self, session: SessionSummary, phase: str, state: str, message: str) -> None:
        now = datetime.now(UTC)
        task = TaskStatus(
            task_id=uuid4().hex[:10],
            phase=phase,  # type: ignore[arg-type]
            state=state,  # type: ignore[arg-type]
            message=message,
            created_at=now,
            updated_at=now,
        )
        self.store.append_task(session.session_id, task)
        self._session_logger(session).info("[%s] %s", phase, message)

    def _analysis_markdown(self, title: str, sections: list[AnalysisSection]) -> str:
        lines = [f"# {title}", ""]
        for section in sections:
            lines.append(f"## {section.title}")
            lines.append(section.content)
            lines.append("")
        return "\n".join(lines).strip() + "\n"

    def _session_logger(self, session: SessionSummary):
        session_dir = self.store.session_dir(session.session_id)
        created_label = session.created_at.strftime("%Y%m%d_%H%M%S")
        return get_session_logger(session_dir, session.session_slug, created_label)
