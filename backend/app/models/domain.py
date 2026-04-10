"""Domain models for sessions, assets, tasks, and reports."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


TaskPhase = Literal["parse", "plan", "analyze", "answer", "verify", "archive"]
TaskStateValue = Literal["pending", "running", "completed", "failed"]
VerificationStatus = Literal["not_needed", "verified_local", "verified_external", "unverified"]


class TaskStatus(BaseModel):
    """Status record for a staged session task."""

    task_id: str
    phase: TaskPhase
    state: TaskStateValue
    message: str
    created_at: datetime
    updated_at: datetime


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
    latest_task: TaskStatus | None = None


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
    page_label: str | None = None


class ParsedDocument(BaseModel):
    """A structured representation of a paper."""

    paper_id: str
    source_path: str
    title: str
    abstract: str
    sections: list[ParsedSection]
    plain_text: str
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

    source_type: Literal["paper", "reference"]
    asset_id: str
    label: str
    excerpt: str
    locator: str | None = None


class ReferenceAsset(BaseModel):
    """External or supplemental source localized into a session."""

    reference_id: str
    title: str
    source_kind: Literal["semantic_scholar", "openalex", "web"]
    source_url: str
    localized_path: str
    summary: str
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
    """Persistent session memory note."""

    session_id: str
    path: str
    confirmed_points: list[str] = Field(default_factory=list)
    unresolved_points: list[str] = Field(default_factory=list)
    tracked_questions: list[str] = Field(default_factory=list)
    paper_titles: list[str] = Field(default_factory=list)
    reference_titles: list[str] = Field(default_factory=list)
    updated_at: datetime


class ArchiveArtifact(BaseModel):
    """Final archive output for a session."""

    archive_id: str
    session_id: str
    markdown_path: str
    created_at: datetime


class SessionArtifacts(BaseModel):
    """Convenience view of assets produced for a session."""

    papers: list[PaperAsset] = Field(default_factory=list)
    references: list[ReferenceAsset] = Field(default_factory=list)
    analyses: list[AnalysisArtifact] = Field(default_factory=list)
    qa_records: list[QARecord] = Field(default_factory=list)
    memory: MemoryNote | None = None
    archive: ArchiveArtifact | None = None
