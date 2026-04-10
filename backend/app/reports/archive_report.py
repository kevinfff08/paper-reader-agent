"""Markdown archive report generation."""

from __future__ import annotations

from backend.app.models.domain import AnalysisArtifact, MemoryNote, QARecord, ReferenceAsset, SessionSummary


class ArchiveReportBuilder:
    """Build the final Markdown archive for a session."""

    def build(
        self,
        *,
        session: SessionSummary,
        analyses: list[AnalysisArtifact],
        qa_records: list[QARecord],
        references: list[ReferenceAsset],
        memory_note: MemoryNote | None,
    ) -> str:
        """Return Markdown archive content."""
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

        lines.extend(["## Follow-up Q&A"])
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

        lines.extend(["", "## Reference List"])
        for reference in references:
            lines.append(f"- {reference.title} ({reference.source_kind})")
        return "\n".join(lines).strip() + "\n"
