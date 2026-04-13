"""API request and response models."""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.app.core.models.domain import (
    AnalysisArtifact,
    ArchiveArtifact,
    DiscoveredPaper,
    LiteratureSearchRecord,
    QARecord,
    ReferenceAsset,
    RunSummary,
    SessionArtifacts,
    SessionSummary,
    TaskSummary,
)


class CreateSessionRequest(BaseModel):
    """Request payload to create a new session."""

    session_name: str = Field(min_length=1)
    categories: list[str] = Field(default_factory=list)
    user_goal: str | None = None
    background: str | None = None
    external_links: list[str] = Field(default_factory=list)


class AnalyzeSessionRequest(BaseModel):
    """Request payload to trigger analysis for a session."""

    focus_question: str | None = None


class AskQuestionRequest(BaseModel):
    """Request payload to ask a follow-up question."""

    question: str = Field(min_length=1)
    preferred_paper_ids: list[str] = Field(default_factory=list)


class ArchiveSessionRequest(BaseModel):
    """Request payload to create an archive report."""

    include_qa: bool = True


class CreateRunRequest(BaseModel):
    """Request payload to create an agent run."""

    mode: str = Field(pattern="^(analyze|answer|archive)$")
    input: str = Field(default="")
    preferred_paper_ids: list[str] = Field(default_factory=list)


class CreateTaskRequest(BaseModel):
    """Request payload to manually create a background specialized-agent task."""

    agent_kind: str = Field(pattern="^(compact|session_memory_update|memory_extraction|verification)$")
    input: str = Field(default="")
    parent_run_id: str | None = None
    snapshot_version: int | None = None


class DiscoverLiteratureRequest(BaseModel):
    """Request payload for synchronous literature discovery."""

    query: str = Field(min_length=1)
    discovery_mode: str = Field(pattern="^(latest_top_venues|seminal|related)$")
    domain: str = Field(pattern="^(general|cs|biomed)$", default="general")
    max_results: int = Field(default=10, ge=1, le=20)
    preferred_venues: list[str] = Field(default_factory=list)


class LocalizeDiscoveryReferenceRequest(BaseModel):
    """Request payload to save one discovered paper as a session reference."""

    result_id: str = Field(min_length=1)


class SessionListResponse(BaseModel):
    """Response payload for session listing."""

    sessions: list[SessionSummary]


class SessionDetailResponse(BaseModel):
    """Response payload for session details."""

    session: SessionSummary
    artifacts: SessionArtifacts


class AnalysisResponse(BaseModel):
    """Response payload for analysis generation."""

    analysis: AnalysisArtifact


class QuestionResponse(BaseModel):
    """Response payload for a question answer."""

    qa_record: QARecord


class ArchiveResponse(BaseModel):
    """Response payload for archive generation."""

    archive: ArchiveArtifact


class RunResponse(BaseModel):
    """Response payload for a run."""

    run: RunSummary


class TaskResponse(BaseModel):
    """Response payload for a background task."""

    task: TaskSummary


class TaskListResponse(BaseModel):
    """Response payload for task history."""

    tasks: list[TaskSummary]


class DiscoverLiteratureResponse(BaseModel):
    """Response payload for one literature discovery execution."""

    search: LiteratureSearchRecord


class LiteratureSearchListResponse(BaseModel):
    """Response payload for search history."""

    searches: list[LiteratureSearchRecord]


class ReferenceResponse(BaseModel):
    """Response payload for one localized reference."""

    reference: ReferenceAsset
