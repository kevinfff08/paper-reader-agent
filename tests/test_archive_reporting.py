from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from backend.app.core.models.domain import (
    AnalysisArtifact,
    AnalysisSection,
    CompactSummary,
    MemoryNote,
    QARecord,
    ReferenceAsset,
    VerificationNote,
)
from backend.app.services.reporting.archive_report import ArchiveReportBuilder
from backend.app.services.reporting.markdown_validator import MarkdownValidator


def _now() -> datetime:
    return datetime.now(UTC)


def test_archive_report_builder_handles_empty_qa() -> None:
    builder = ArchiveReportBuilder()
    result = builder.build(
        session=_session(),
        analyses=[
            AnalysisArtifact(
                analysis_id="analysis-1",
                session_id="session-1",
                paper_ids=["paper-1"],
                title="Single-Paper Analysis: A Great Paper",
                sections=[AnalysisSection(key="core", title="Core Contribution", content="A grounded analysis section.")],
                markdown_path="analysis.md",
                created_at=_now(),
            )
        ],
        qa_records=[],
        references=[],
        memory_note=None,
        output_dir=Path.cwd(),
    )

    assert "## Initial Analysis" in result.markdown
    assert "## Consolidated Q&A Insights" in result.markdown
    assert "No follow-up questions were recorded for this session." in result.markdown
    assert "## Appendix: Raw Follow-up Q&A" in result.markdown


def test_archive_report_builder_synthesizes_qa_and_preserves_appendix() -> None:
    builder = ArchiveReportBuilder()
    record_1 = QARecord(
        question_id="q1",
        question_text="What do the experiments evaluate?",
        answer_text="The experiments evaluate generalization and robustness across two benchmarks.",
        verification_status="verified_uploaded_paper",
        created_at=_now(),
    )
    record_2 = QARecord(
        question_id="q2",
        question_text="Which benchmarks are used in the experiments?",
        answer_text="The evidence suggests two benchmarks are used, but the exact split remains partially unclear.",
        verification_status="unverified",
        retrieval_refs=[
            ReferenceAsset(
                reference_id="ref-1",
                title="Benchmark Companion",
                source_kind="web",
                source_url="https://example.org/benchmark",
                summary="Provides benchmark context.",
                created_at=_now(),
            )
        ],
        created_at=_now(),
    )
    result = builder.build(
        session=_session(),
        analyses=[],
        qa_records=[record_1, record_2],
        references=record_2.retrieval_refs,
        memory_note=MemoryNote(
            session_id="session-1",
            path="",
            unresolved_points=["Exact benchmark split remains unclear"],
            updated_at=_now(),
        ),
        verification_notes=[
            VerificationNote(
                verification_id="ver-1",
                session_id="session-1",
                question_text=record_1.question_text,
                status="passed",
                rationale="Uploaded-paper evidence supports the evaluation scope.",
                created_at=_now(),
            )
        ],
        compact_summaries=[
            CompactSummary(
                summary_id="sum-1",
                session_id="session-1",
                boundary_label="qa:experiments",
                content="The session repeatedly revisited experimental evidence.",
                created_at=_now(),
            )
        ],
        output_dir=Path.cwd(),
    )

    assert "### Stable Conclusions" in result.markdown
    assert "### Open Issues and Evidence Gaps" in result.markdown
    assert "Exact benchmark split remains unclear" in result.markdown
    assert "## Appendix: Raw Follow-up Q&A" in result.markdown
    assert "### Q: What do the experiments evaluate?" in result.markdown
    assert "### Q: Which benchmarks are used in the experiments?" in result.markdown


def test_archive_report_builder_falls_back_when_llm_summary_fails() -> None:
    builder = ArchiveReportBuilder(llm_client=_FailingLLM())
    result = builder.build(
        session=_session(),
        analyses=[],
        qa_records=[
            QARecord(
                question_id="q1",
                question_text="How does the method behave under ablation?",
                answer_text="The ablation evidence suggests the first component dominates performance.",
                verification_status="verified_session_local",
                created_at=_now(),
            )
        ],
        references=[],
        memory_note=None,
        output_dir=Path.cwd(),
    )

    assert "### Stable Conclusions" in result.markdown
    assert "How does the method behave under ablation?" in result.markdown


def test_markdown_validator_warns_and_applies_safe_repairs(isolated_session_root: Path) -> None:
    validator = MarkdownValidator()
    markdown = "\n".join(
        [
            "# Title",
            "### Jumped Heading",
            "",
            "```mermaid",
            "invalid diagram",
            "```",
            "",
            "![missing](missing.png)",
            "",
            "| Col A | Col B |",
            "| --- | --- |",
            "| only one |",
            "",
            "$unbalanced math",
            "",
            "<script>alert('x')</script>",
            "",
            "```python",
            "print('hello')",
        ]
    )
    result = validator.validate(markdown, base_dir=isolated_session_root)
    warning_types = {warning.warning_type for warning in result.warnings}

    assert "heading_jump" in warning_types
    assert "invalid_mermaid" in warning_types
    assert "missing_image" in warning_types
    assert "table_shape" in warning_types
    assert "math_balance" in warning_types
    assert "raw_html_stripped" in warning_types
    assert "unclosed_fence" in warning_types
    assert "```mermaid" not in result.markdown
    assert result.markdown.rstrip().endswith("```")


def _session():
    return type(
        "SessionStub",
        (),
        {
            "session_name": "Archive Session",
            "session_id": "session-1",
            "created_at": _now(),
            "categories": ["ml"],
            "user_goal": "Read carefully",
            "background": None,
        },
    )()


class _FailingLLM:
    is_configured = True

    def generate(self, *args, **kwargs):
        raise RuntimeError("synthetic failure")
