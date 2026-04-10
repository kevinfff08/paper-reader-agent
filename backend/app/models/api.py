"""API request and response models."""

from __future__ import annotations

from pydantic import BaseModel, Field

from backend.app.models.domain import (
    AnalysisArtifact,
    ArchiveArtifact,
    QARecord,
    SessionArtifacts,
    SessionSummary,
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
