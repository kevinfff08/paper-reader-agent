"""Domain models for sessions, assets, runs, and layered memory."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


VerificationStatus = Literal[
    "not_needed",
    "verified_uploaded_paper",
    "verified_session_local",
    "supplemented_external",
    "links_only",
    "unverified",
]
RunMode = Literal["analyze", "answer", "archive"]
RunStateValue = Literal["pending", "running", "completed", "failed"]
RiskLevel = Literal["low", "medium", "high"]
VerificationState = Literal["not_requested", "pending", "passed", "failed"]
RunEventType = Literal[
    "run_started",
    "assistant_delta",
    "tool_call_started",
    "tool_call_finished",
    "evidence_added",
    "verification_required",
    "memory_updated",
    "run_completed",
    "run_failed",
]
TaskAgentKind = Literal["compact", "session_memory_update", "memory_extraction", "verification"]
TaskStatus = Literal["pending", "running", "completed", "failed", "cancelled"]
TaskEventType = Literal[
    "task_started",
    "task_progress",
    "task_log",
    "task_output",
    "task_completed",
    "task_failed",
    "task_cancelled",
]
DiscoveryMode = Literal["latest_top_venues", "seminal", "related", "supporting_context"]
DiscoveryDomain = Literal["general", "cs", "biomed"]
ReferenceSourceKind = Literal[
    "semantic_scholar",
    "openalex",
    "crossref",
    "pubmed",
    "europe_pmc",
    "openreview",
    "acl",
    "cvf",
    "pmlr",
    "arxiv",
    "web",
]
AcquisitionStatus = Literal[
    "localized_fulltext",
    "localized_summary",
    "remote_pdf",
    "remote_landing_only",
    "metadata_only",
]
OaStatus = Literal["open", "closed", "unknown"]


class SessionSummary(BaseModel):
    """Top-level session metadata."""

    session_id: str
    session_name: str
    session_slug: str
    categories: list[str] = Field(default_factory=list)
    user_goal: str | None = None
    background: str | None = None
    external_links: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class PaperAsset(BaseModel):
    """A locally stored uploaded paper."""

    paper_id: str
    filename: str
    media_type: str
    original_path: str
    parsed_path: str | None = None
    title: str | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    created_at: datetime


class ParsedSection(BaseModel):
    """A parsed section from a paper."""

    heading: str
    content: str
    section_id: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    section_path: str | None = None
    page_label: str | None = None


class ParsedChunk(BaseModel):
    """A smaller retrievable chunk derived from parsed sections."""

    chunk_id: str
    heading: str
    content: str
    chunk_type: Literal["narrative", "table", "figure"] = "narrative"
    page_start: int | None = None
    page_end: int | None = None
    section_path: str | None = None
    table_refs: list[str] = Field(default_factory=list)
    picture_refs: list[str] = Field(default_factory=list)
    rank_text: str | None = None
    page_label: str | None = None


class ParsedTable(BaseModel):
    """A normalized table extracted from a paper."""

    table_id: str
    caption: str = ""
    page_label: str | None = None
    locator: str | None = None
    markdown: str = ""
    nearby_text: str = ""


class ParsedPicture(BaseModel):
    """A normalized picture region extracted from a paper."""

    picture_id: str
    caption: str = ""
    page_label: str | None = None
    locator: str | None = None
    nearby_text: str = ""
    bbox: list[float] = Field(default_factory=list)


class ParsedDocument(BaseModel):
    """A structured representation of a paper."""

    paper_id: str
    source_path: str
    title: str
    abstract: str
    sections: list[ParsedSection]
    chunks: list[ParsedChunk] = Field(default_factory=list)
    plain_text: str
    parser_backend: Literal["docling", "legacy"] = "legacy"
    parser_version: str = "legacy-v1"
    page_count: int | None = None
    docling_json_path: str | None = None
    markdown_path: str | None = None
    tables: list[ParsedTable] = Field(default_factory=list)
    pictures: list[ParsedPicture] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)
    created_at: datetime


class AnalysisSection(BaseModel):
    """One section of a structured analysis artifact."""

    key: str
    title: str
    content: str


class AnalysisArtifact(BaseModel):
    """Structured analysis for a session or paper group."""

    analysis_id: str
    session_id: str
    paper_ids: list[str]
    title: str
    sections: list[AnalysisSection]
    markdown_path: str
    created_at: datetime


class EvidenceRef(BaseModel):
    """A traceable source reference used in analysis or QA."""

    source_type: Literal["paper", "analysis", "reference"]
    asset_id: str
    label: str
    excerpt: str
    locator: str | None = None
    source_kind: ReferenceSourceKind | None = None
    source_url: str | None = None
    page_label: str | None = None
    score: float | None = None


class DiscoveredPaper(BaseModel):
    """One literature-discovery result."""

    result_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    source_kind: ReferenceSourceKind
    source_url: str
    doi: str | None = None
    citation_count: int | None = None
    summary: str = ""
    landing_page_url: str | None = None
    pdf_url: str | None = None
    best_access_url: str | None = None
    manual_search_url: str | None = None
    oa_status: OaStatus = "unknown"
    acquisition_status: AcquisitionStatus = "metadata_only"
    search_reason: str | None = None
    is_supplementary: bool = False


class LiteratureSearchRecord(BaseModel):
    """A persisted discovery query and its results."""

    search_id: str
    session_id: str
    query: str
    discovery_mode: DiscoveryMode
    domain: DiscoveryDomain
    preferred_venues: list[str] = Field(default_factory=list)
    results: list[DiscoveredPaper] = Field(default_factory=list)
    created_at: datetime


class ReferenceAsset(BaseModel):
    """External or supplemental source localized into a session."""

    reference_id: str
    title: str
    source_kind: ReferenceSourceKind
    source_url: str
    localized_path: str | None = None
    summary: str = ""
    doi: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    citation_count: int | None = None
    landing_page_url: str | None = None
    pdf_url: str | None = None
    best_access_url: str | None = None
    manual_search_url: str | None = None
    oa_status: OaStatus = "unknown"
    acquisition_status: AcquisitionStatus = "metadata_only"
    search_reason: str | None = None
    is_supplementary: bool = False
    created_at: datetime


class QARecord(BaseModel):
    """One question-answer exchange inside a session."""

    question_id: str
    question_text: str
    answer_text: str
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    retrieval_refs: list[ReferenceAsset] = Field(default_factory=list)
    verification_status: VerificationStatus = "unverified"
    created_at: datetime


class MemoryNote(BaseModel):
    """Working-memory note for a session."""

    session_id: str
    path: str
    confirmed_points: list[str] = Field(default_factory=list)
    unresolved_points: list[str] = Field(default_factory=list)
    tracked_questions: list[str] = Field(default_factory=list)
    paper_titles: list[str] = Field(default_factory=list)
    reference_titles: list[str] = Field(default_factory=list)
    updated_at: datetime


class EvidenceLedgerEntry(BaseModel):
    """Non-compressible evidence stored for later verification."""

    evidence_id: str
    session_id: str
    run_id: str | None = None
    source_type: Literal["paper", "analysis", "reference"]
    asset_id: str
    label: str
    excerpt: str
    locator: str | None = None
    recorded_at: datetime


class CompactSummary(BaseModel):
    """A compact boundary summary for a session."""

    summary_id: str
    session_id: str
    boundary_label: str
    content: str
    boundary_id: str | None = None
    snapshot_version: int | None = None
    preserved_tail_anchor: str | None = None
    restored_context_refs: list[str] = Field(default_factory=list)
    created_at: datetime


class LibraryCard(BaseModel):
    """Cross-session local card for papers or concepts."""

    card_id: str
    session_id: str
    card_type: Literal["paper", "concept", "session"]
    title: str
    content: str
    linked_asset_ids: list[str] = Field(default_factory=list)
    created_at: datetime


class ArchiveArtifact(BaseModel):
    """Final archive output for a session."""

    archive_id: str
    session_id: str
    markdown_path: str
    created_at: datetime


class VerificationNote(BaseModel):
    """Short-lived verification memory for high-risk question handling."""

    verification_id: str
    session_id: str
    run_id: str | None = None
    question_text: str
    status: VerificationState
    rationale: str
    evidence_labels: list[str] = Field(default_factory=list)
    created_at: datetime


class WorkingStateSnapshot(BaseModel):
    """Frozen working-state view consumed by background agents."""

    snapshot_id: str
    session_id: str
    run_id: str | None = None
    version: int
    transcript_cursor: int
    active_question: str | None = None
    unresolved_items: list[str] = Field(default_factory=list)
    active_plan: list[str] = Field(default_factory=list)
    recent_evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    recent_file_paths: list[str] = Field(default_factory=list)
    preserved_tail: list[str] = Field(default_factory=list)
    created_at: datetime


class RunSummary(BaseModel):
    """A persisted agent runtime execution."""

    run_id: str
    session_id: str
    mode: RunMode
    status: RunStateValue
    input_text: str
    preferred_paper_ids: list[str] = Field(default_factory=list)
    risk_level: RiskLevel | None = None
    working_state_version: int = 0
    active_background_task_ids: list[str] = Field(default_factory=list)
    verification_state: VerificationState | None = None
    final_artifact_ref: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class RunEvent(BaseModel):
    """One event emitted by the run engine."""

    event_id: str
    run_id: str
    sequence_number: int
    event_type: RunEventType
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class TaskSummary(BaseModel):
    """A persisted specialized-agent task."""

    task_id: str
    session_id: str
    agent_kind: TaskAgentKind
    status: TaskStatus
    parent_run_id: str | None = None
    input_text: str = ""
    snapshot_version: int | None = None
    progress: int = 0
    current_step: str | None = None
    output_preview: str | None = None
    result_payload: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class TaskEvent(BaseModel):
    """One event emitted by the background task engine."""

    event_id: str
    task_id: str
    sequence_number: int
    event_type: TaskEventType
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class SessionFileEntry(BaseModel):
    """One file or generated artifact exposed in the session file manager."""

    file_id: str
    label: str
    path: str
    category: Literal[
        "paper",
        "parsed",
        "reference",
        "analysis",
        "archive",
        "memory",
        "task",
    ]
    updated_at: datetime | None = None


class SessionArtifacts(BaseModel):
    """Convenience view of assets produced for a session."""

    papers: list[PaperAsset] = Field(default_factory=list)
    references: list[ReferenceAsset] = Field(default_factory=list)
    analyses: list[AnalysisArtifact] = Field(default_factory=list)
    qa_records: list[QARecord] = Field(default_factory=list)
    memory: MemoryNote | None = None
    evidence_ledger: list[EvidenceLedgerEntry] = Field(default_factory=list)
    compact_summaries: list[CompactSummary] = Field(default_factory=list)
    library_cards: list[LibraryCard] = Field(default_factory=list)
    verification_memory: list[VerificationNote] = Field(default_factory=list)
    literature_searches: list[LiteratureSearchRecord] = Field(default_factory=list)
    runs: list[RunSummary] = Field(default_factory=list)
    tasks: list[TaskSummary] = Field(default_factory=list)
    session_files: list[SessionFileEntry] = Field(default_factory=list)
    archive: ArchiveArtifact | None = None
