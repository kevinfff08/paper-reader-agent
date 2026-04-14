"""Q&A synthesis for archive-time report generation."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from backend.app.core.models.domain import CompactSummary, MemoryNote, QARecord, ReferenceAsset, VerificationNote
from backend.app.llm.client import LLMClient


_STOPWORDS = {
    "about",
    "after",
    "against",
    "also",
    "among",
    "because",
    "between",
    "could",
    "does",
    "from",
    "have",
    "into",
    "more",
    "should",
    "than",
    "that",
    "their",
    "them",
    "there",
    "these",
    "they",
    "this",
    "what",
    "when",
    "where",
    "which",
    "while",
    "with",
    "would",
}

_STABLE_STATUSES = {"verified_uploaded_paper", "verified_session_local"}
_TENTATIVE_STATUSES = {"supplemented_external", "links_only", "unverified"}


def _tokenize(text: str) -> list[str]:
    cleaned = re.sub(r"[^A-Za-z0-9]+", " ", text.lower())
    return [token for token in cleaned.split() if len(token) > 2 and token not in _STOPWORDS]


def _snippet(text: str, limit: int = 240) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


@dataclass(slots=True)
class _QuestionGroup:
    """One thematic cluster of related questions."""

    title: str
    tokens: set[str]
    records: list[QARecord] = field(default_factory=list)


class QASummaryBuilder:
    """Synthesize archive-ready Markdown from session Q&A records."""

    def __init__(self, llm_client: LLMClient | None = None):
        self.llm_client = llm_client

    def build(
        self,
        *,
        qa_records: list[QARecord],
        references: list[ReferenceAsset],
        memory_note: MemoryNote | None,
        verification_notes: list[VerificationNote],
        compact_summaries: list[CompactSummary] | None = None,
    ) -> str:
        """Return a synthesized Markdown section for report use."""
        if not qa_records:
            return "No follow-up questions were recorded for this session."

        compact_summaries = compact_summaries or []
        if self.llm_client and self.llm_client.is_configured:
            prompt = self._build_llm_prompt(
                qa_records=qa_records,
                references=references,
                memory_note=memory_note,
                verification_notes=verification_notes,
                compact_summaries=compact_summaries,
            )
            try:
                return self.llm_client.generate(
                    prompt,
                    system=(
                        "You are preparing publishable Markdown for a research-reading archive. "
                        "Write in an academic, neutral tone. Consolidate overlapping questions by theme, "
                        "separate stable conclusions from tentative synthesis, surface unresolved questions, "
                        "and integrate useful supplementary references into the narrative. "
                        "Do not write conversational chat summaries."
                    ),
                    max_tokens=1800,
                )
            except Exception:
                pass
        return self._build_heuristic_summary(
            qa_records=qa_records,
            references=references,
            memory_note=memory_note,
            verification_notes=verification_notes,
        )

    def _build_llm_prompt(
        self,
        *,
        qa_records: list[QARecord],
        references: list[ReferenceAsset],
        memory_note: MemoryNote | None,
        verification_notes: list[VerificationNote],
        compact_summaries: list[CompactSummary],
    ) -> str:
        question_blocks: list[str] = []
        for index, record in enumerate(qa_records, start=1):
            evidence_labels = ", ".join(ref.label for ref in record.evidence_refs[:4]) or "None"
            localized_titles = ", ".join(ref.title for ref in record.retrieval_refs[:4]) or "None"
            question_blocks.append(
                (
                    f"Q{index}: {record.question_text}\n"
                    f"Verification: {record.verification_status}\n"
                    f"Evidence: {evidence_labels}\n"
                    f"Localized references: {localized_titles}\n"
                    f"Answer excerpt: {_snippet(record.answer_text, 420)}"
                )
            )

        verification_lines = [
            f"- {note.question_text}: {note.status} ({note.rationale})"
            for note in verification_notes[:8]
        ] or ["- None"]

        reference_lines = [
            f"- {reference.title}: {_snippet(reference.summary, 160)}"
            for reference in references[:8]
        ] or ["- None"]

        compact_lines = [
            f"- {summary.boundary_label}: {_snippet(summary.content, 160)}"
            for summary in compact_summaries[:6]
        ] or ["- None"]

        memory_lines = ["- None"]
        if memory_note is not None:
            memory_lines = [
                f"- Confirmed points: {', '.join(memory_note.confirmed_points[:6]) or 'None'}",
                f"- Unresolved points: {', '.join(memory_note.unresolved_points[:6]) or 'None'}",
                f"- Tracked questions: {', '.join(memory_note.tracked_questions[:6]) or 'None'}",
            ]

        return (
            "Produce a Markdown section suitable for the main body of a final archive report.\n\n"
            "Requirements:\n"
            "- Consolidate questions by theme instead of chronology.\n"
            "- Distinguish stable conclusions from tentative synthesis.\n"
            "- Identify unresolved questions and evidence gaps.\n"
            "- Integrate useful localized references into the prose.\n"
            "- Keep the prose publishable and concise; use lists only when they help readability.\n\n"
            f"Q&A records:\n\n{chr(10).join(question_blocks)}\n\n"
            f"Verification notes:\n{chr(10).join(verification_lines)}\n\n"
            f"Localized references:\n{chr(10).join(reference_lines)}\n\n"
            f"Memory note:\n{chr(10).join(memory_lines)}\n\n"
            f"Compact continuity notes:\n{chr(10).join(compact_lines)}"
        )

    def _build_heuristic_summary(
        self,
        *,
        qa_records: list[QARecord],
        references: list[ReferenceAsset],
        memory_note: MemoryNote | None,
        verification_notes: list[VerificationNote],
    ) -> str:
        groups = self._cluster_questions(qa_records)
        stable_sections: list[str] = []
        tentative_sections: list[str] = []
        open_items: list[str] = []

        verification_by_question = {note.question_text: note for note in verification_notes}

        for group in groups:
            latest = sorted(group.records, key=lambda item: item.created_at)[-1]
            statuses = {record.verification_status for record in group.records}
            evidence_line = ", ".join(ref.label for ref in latest.evidence_refs[:3]) or "No strong local evidence recorded."
            refs_line = ", ".join(ref.title for ref in latest.retrieval_refs[:3])
            rendered = [
                f"**Theme:** {group.title}",
                "",
                _snippet(latest.answer_text, 320),
                "",
                f"Evidence anchors: {evidence_line}",
            ]
            if refs_line:
                rendered.append(f"Supplementary references: {refs_line}")
            note = verification_by_question.get(latest.question_text)
            if note is not None:
                rendered.append(f"Verification note: {note.rationale}")
            block = "\n".join(rendered)
            if statuses & _STABLE_STATUSES:
                stable_sections.append(block)
            else:
                tentative_sections.append(block)
            if statuses <= _TENTATIVE_STATUSES or latest.verification_status == "unverified":
                open_items.append(group.title)

        if memory_note is not None:
            open_items.extend(memory_note.unresolved_points[:6])

        reference_section = ""
        discovered_titles = [reference.title for reference in references if reference.summary][:6]
        if discovered_titles:
            reference_section = (
                "## Useful Supplementary References\n\n"
                "The Q&A phase introduced the following references that may warrant follow-up reading: "
                + ", ".join(dict.fromkeys(discovered_titles))
                + "."
            )

        lines = ["### Stable Conclusions", ""]
        if stable_sections:
            for section in stable_sections:
                lines.append(section)
                lines.append("")
        else:
            lines.append("No stable conclusions were extracted from the follow-up Q&A.")
            lines.append("")

        if tentative_sections:
            lines.extend(["### Tentative Synthesis", ""])
            for section in tentative_sections:
                lines.append(section)
                lines.append("")

        deduped_open = [item for item, _ in Counter(open_items).most_common()]
        if deduped_open:
            lines.extend(["### Open Issues and Evidence Gaps", ""])
            for item in deduped_open[:8]:
                lines.append(f"- {item}")
            lines.append("")

        if reference_section:
            lines.append(reference_section)
            lines.append("")
        return "\n".join(lines).strip()

    def _cluster_questions(self, qa_records: list[QARecord]) -> list[_QuestionGroup]:
        groups: list[_QuestionGroup] = []
        for record in sorted(qa_records, key=lambda item: item.created_at):
            tokens = set(_tokenize(record.question_text))
            best_group: _QuestionGroup | None = None
            best_score = 0.0
            for group in groups:
                if not tokens or not group.tokens:
                    continue
                overlap = len(tokens & group.tokens)
                score = overlap / max(len(tokens | group.tokens), 1)
                if overlap >= 2 or score >= 0.25:
                    if score > best_score:
                        best_score = score
                        best_group = group
            if best_group is None:
                groups.append(_QuestionGroup(title=record.question_text, tokens=tokens, records=[record]))
                continue
            best_group.records.append(record)
            best_group.tokens |= tokens
        return groups
