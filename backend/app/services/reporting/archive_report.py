"""Markdown archive report generation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backend.app.core.models.domain import (
    AnalysisArtifact,
    CompactSummary,
    LibraryCard,
    MemoryNote,
    QARecord,
    ReferenceAsset,
    SessionSummary,
    VerificationNote,
)
from backend.app.llm.client import LLMClient
from backend.app.services.reporting.markdown_validator import MarkdownValidator, ValidationResult
from backend.app.services.reporting.qa_summary import QASummaryBuilder


@dataclass(slots=True)
class ArchiveBuildResult:
    """Final archive output plus validation metadata."""

    markdown: str
    validation: ValidationResult


class ArchiveReportBuilder:
    """Build the final Markdown archive for a session."""

    def __init__(self, llm_client: LLMClient | None = None):
        self.qa_summary_builder = QASummaryBuilder(llm_client=llm_client)
        self.markdown_validator = MarkdownValidator()

    def build(
        self,
        *,
        session: SessionSummary,
        analyses: list[AnalysisArtifact],
        qa_records: list[QARecord],
        references: list[ReferenceAsset],
        memory_note: MemoryNote | None,
        compact_summaries: list[CompactSummary] | None = None,
        library_cards: list[LibraryCard] | None = None,
        verification_notes: list[VerificationNote] | None = None,
        output_dir: Path | None = None,
    ) -> ArchiveBuildResult:
        """Return archive Markdown content and validation metadata."""
        compact_summaries = compact_summaries or []
        library_cards = library_cards or []
        verification_notes = verification_notes or []
        qa_summary = self.qa_summary_builder.build(
            qa_records=qa_records,
            references=references,
            memory_note=memory_note,
            verification_notes=verification_notes,
            compact_summaries=compact_summaries,
        )

        lines = [
            f"# Session Archive: {session.session_name}",
            "",
            "## Session Metadata",
            f"- Session ID: `{session.session_id}`",
            f"- Created At: {session.created_at.isoformat()}",
            f"- Categories: {', '.join(session.categories) if session.categories else 'None'}",
        ]
        if session.user_goal:
            lines.append(f"- User Goal: {session.user_goal}")
        if session.background:
            lines.append(f"- Background: {session.background}")

        lines.extend(["", "## Initial Analysis"])
        for analysis in analyses:
            lines.append(f"### {analysis.title}")
            for section in analysis.sections:
                lines.append(f"#### {section.title}")
                lines.append(section.content)
                lines.append("")

        lines.extend(["## Consolidated Q&A Insights", qa_summary, ""])

        lines.extend(["## Localized References"])
        if not references:
            lines.append("No supplemental references were localized.")
        for reference in references:
            lines.append(f"- [{reference.title}]({reference.source_url})")

        lines.extend(["", "## Memory Note Summary"])
        if memory_note is None:
            lines.append("No memory note available.")
        else:
            lines.append("### Confirmed Points")
            lines.extend([f"- {item}" for item in memory_note.confirmed_points] or ["- None"])
            lines.append("### Unresolved Points")
            lines.extend([f"- {item}" for item in memory_note.unresolved_points] or ["- None"])
            lines.append("### Tracked Questions")
            lines.extend([f"- {item}" for item in memory_note.tracked_questions] or ["- None"])

        lines.extend(["", "## Compact Summaries"])
        if not compact_summaries:
            lines.append("No compact summaries available.")
        for summary in compact_summaries:
            lines.append(f"### {summary.boundary_label}")
            lines.append(summary.content)
            lines.append("")

        lines.extend(["## Library Cards"])
        if not library_cards:
            lines.append("No library cards available.")
        for card in library_cards:
            lines.append(f"### {card.title} ({card.card_type})")
            lines.append(card.content)
            if card.linked_asset_ids:
                lines.append(f"- Linked assets: {', '.join(card.linked_asset_ids)}")
            lines.append("")

        lines.extend(["", "## Reference List"])
        for reference in references:
            lines.append(f"- {reference.title} ({reference.source_kind})")

        lines.extend(["", "## Appendix: Raw Follow-up Q&A"])
        if not qa_records:
            lines.append("No follow-up questions recorded.")
        for record in qa_records:
            lines.append(f"### Q: {record.question_text}")
            lines.append(record.answer_text)
            lines.append(f"- Verification: `{record.verification_status}`")
            if record.evidence_refs:
                lines.append("- Evidence:")
                for evidence in record.evidence_refs:
                    lines.append(f"  - {evidence.label}: {evidence.excerpt[:160]}")
            if record.retrieval_refs:
                lines.append("- New References:")
                for reference in record.retrieval_refs:
                    lines.append(f"  - [{reference.title}]({reference.source_url})")
            lines.append("")

        markdown = "\n".join(lines).strip() + "\n"
        validation = self.markdown_validator.validate(markdown, base_dir=output_dir)
        return ArchiveBuildResult(markdown=validation.markdown, validation=validation)
