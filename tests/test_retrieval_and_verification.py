from datetime import UTC, datetime

from backend.app.core.models.domain import (
    AnalysisArtifact,
    AnalysisSection,
    EvidenceRef,
    ParsedChunk,
    ParsedDocument,
    ParsedSection,
    QARecord,
    ReferenceAsset,
)
from backend.app.services.retrieval.local_evidence import LocalEvidenceRetriever
from backend.app.services.verification.verifier import AnswerVerifier


def test_local_evidence_retriever_prefers_paper_chunks() -> None:
    retriever = LocalEvidenceRetriever()
    now = datetime.now(UTC)
    parsed_doc = ParsedDocument(
        paper_id="paper-1",
        source_path="paper.txt",
        title="Sample Paper",
        abstract="",
        sections=[ParsedSection(heading="Method", content="The method uses a sparse attention mechanism.", page_label="3")],
        chunks=[ParsedChunk(chunk_id="1", heading="Method", content="The method uses a sparse attention mechanism.", page_label="3")],
        plain_text="The method uses a sparse attention mechanism.",
        created_at=now,
    )
    analysis = AnalysisArtifact(
        analysis_id="analysis-1",
        session_id="session-1",
        paper_ids=["paper-1"],
        title="Analysis",
        sections=[AnalysisSection(key="method", title="Method", content="This is a summary of the method.")],
        markdown_path="analysis.md",
        created_at=now,
    )
    reference = ReferenceAsset(
        reference_id="ref-1",
        title="Reference",
        source_kind="openalex",
        source_url="https://example.org",
        summary="Sparse attention background article.",
        created_at=now,
    )

    results = retriever.retrieve(
        "sparse attention method",
        parsed_docs=[parsed_doc],
        analyses=[analysis],
        qa_records=[],
        references=[reference],
        limit=3,
    )

    assert results
    assert results[0].source_type == "paper"
    assert results[0].page_label == "3"


def test_local_evidence_retriever_biases_table_chunks() -> None:
    retriever = LocalEvidenceRetriever()
    now = datetime.now(UTC)
    parsed_doc = ParsedDocument(
        paper_id="paper-1",
        source_path="paper.txt",
        title="Sample Paper",
        abstract="",
        sections=[ParsedSection(heading="Results", content="Results section.", page_label="5")],
        chunks=[
            ParsedChunk(
                chunk_id="narrative-1",
                heading="Results",
                content="We report strong benchmark gains.",
                page_label="5",
                rank_text="results benchmark gains narrative",
            ),
            ParsedChunk(
                chunk_id="table-1",
                heading="Ablation Table",
                content="Table ablation metric accuracy latency.",
                chunk_type="table",
                table_refs=["table-1"],
                page_label="6",
                rank_text="table ablation dataset metric result accuracy latency",
            ),
        ],
        plain_text="Results section.",
        created_at=now,
    )

    results = retriever.retrieve(
        "ablation table metric result",
        parsed_docs=[parsed_doc],
        analyses=[],
        qa_records=[],
        references=[],
        limit=2,
    )

    assert results
    assert results[0].locator and "table-1" in results[0].locator


def test_local_evidence_retriever_biases_figure_chunks() -> None:
    retriever = LocalEvidenceRetriever()
    now = datetime.now(UTC)
    parsed_doc = ParsedDocument(
        paper_id="paper-1",
        source_path="paper.txt",
        title="Sample Paper",
        abstract="",
        sections=[ParsedSection(heading="Method", content="Method section.", page_label="2")],
        chunks=[
            ParsedChunk(
                chunk_id="narrative-1",
                heading="Method",
                content="The method uses sparse attention.",
                page_label="2",
                rank_text="method sparse attention narrative",
            ),
            ParsedChunk(
                chunk_id="figure-1",
                heading="Architecture Diagram",
                content="Figure architecture pipeline overview.",
                chunk_type="figure",
                picture_refs=["figure-1"],
                page_label="3",
                rank_text="figure architecture diagram pipeline overview",
            ),
        ],
        plain_text="Method section.",
        created_at=now,
    )

    results = retriever.retrieve(
        "architecture diagram figure",
        parsed_docs=[parsed_doc],
        analyses=[],
        qa_records=[],
        references=[],
        limit=2,
    )

    assert results
    assert results[0].locator and "figure-1" in results[0].locator


def test_answer_verifier_uses_new_statuses() -> None:
    verifier = AnswerVerifier()
    paper_evidence = [EvidenceRef(source_type="paper", asset_id="paper-1", label="Method", excerpt="text")]
    analysis_evidence = [EvidenceRef(source_type="analysis", asset_id="analysis-1", label="Summary", excerpt="text")]

    assert verifier.verify(evidence_refs=paper_evidence, used_external_sources=False) == "verified_uploaded_paper"
    assert verifier.verify(evidence_refs=analysis_evidence, used_external_sources=False) == "verified_session_local"
    assert verifier.verify(evidence_refs=analysis_evidence, used_external_sources=True) == "supplemented_external"
    assert verifier.verify(evidence_refs=[], used_external_sources=True) == "links_only"
    assert verifier.verify(evidence_refs=[], used_external_sources=False) == "unverified"
