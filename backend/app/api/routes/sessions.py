"""Session-centric REST routes."""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from backend.app.models.api import (
    AnalysisResponse,
    AnalyzeSessionRequest,
    ArchiveResponse,
    ArchiveSessionRequest,
    AskQuestionRequest,
    CreateSessionRequest,
    QuestionResponse,
    SessionDetailResponse,
    SessionListResponse,
)


router = APIRouter(tags=["sessions"])


@router.post("/sessions", response_model=SessionDetailResponse)
def create_session(request: Request, payload: CreateSessionRequest) -> SessionDetailResponse:
    store = request.app.state.store
    session = store.create_session(
        session_name=payload.session_name,
        categories=payload.categories,
        user_goal=payload.user_goal,
        background=payload.background,
        external_links=payload.external_links,
    )
    return SessionDetailResponse(session=session, artifacts=store.get_artifacts(session.session_id))


@router.get("/sessions", response_model=SessionListResponse)
def list_sessions(request: Request) -> SessionListResponse:
    store = request.app.state.store
    return SessionListResponse(sessions=store.list_sessions())


@router.get("/sessions/{session_id}", response_model=SessionDetailResponse)
def get_session(request: Request, session_id: str) -> SessionDetailResponse:
    store = request.app.state.store
    try:
        session = store.get_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return SessionDetailResponse(session=session, artifacts=store.get_artifacts(session_id))


@router.post("/sessions/{session_id}/papers", response_model=SessionDetailResponse)
async def upload_papers(
    request: Request,
    session_id: str,
    files: list[UploadFile] = File(...),
) -> SessionDetailResponse:
    store = request.app.state.store
    try:
        session = store.get_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    for file in files:
        content = await file.read()
        store.save_uploaded_paper(
            session_id,
            filename=file.filename or "upload.bin",
            media_type=file.content_type or "application/octet-stream",
            content=content,
        )
    return SessionDetailResponse(session=session, artifacts=store.get_artifacts(session_id))


@router.post("/sessions/{session_id}/analyze", response_model=AnalysisResponse)
def analyze_session(
    request: Request,
    session_id: str,
    payload: AnalyzeSessionRequest,
) -> AnalysisResponse:
    orchestrator = request.app.state.orchestrator
    try:
        analysis = orchestrator.analyze_session(session_id, focus_question=payload.focus_question)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return AnalysisResponse(analysis=analysis)


@router.get("/sessions/{session_id}/analysis", response_model=list[AnalysisResponse])
def list_analyses(request: Request, session_id: str) -> list[AnalysisResponse]:
    store = request.app.state.store
    return [AnalysisResponse(analysis=item) for item in store.list_analyses(session_id)]


@router.post("/sessions/{session_id}/questions", response_model=QuestionResponse)
def ask_question(
    request: Request,
    session_id: str,
    payload: AskQuestionRequest,
) -> QuestionResponse:
    orchestrator = request.app.state.orchestrator
    record = orchestrator.answer_question(
        session_id,
        payload.question,
        preferred_paper_ids=payload.preferred_paper_ids,
    )
    return QuestionResponse(qa_record=record)


@router.get("/sessions/{session_id}/qa", response_model=list[QuestionResponse])
def list_qa(request: Request, session_id: str) -> list[QuestionResponse]:
    store = request.app.state.store
    return [QuestionResponse(qa_record=item) for item in store.list_qa_records(session_id)]


@router.post("/sessions/{session_id}/archive", response_model=ArchiveResponse)
def build_archive(
    request: Request,
    session_id: str,
    payload: ArchiveSessionRequest,
) -> ArchiveResponse:
    del payload
    orchestrator = request.app.state.orchestrator
    archive = orchestrator.build_archive(session_id)
    return ArchiveResponse(archive=archive)


@router.get("/sessions/{session_id}/artifacts", response_model=SessionDetailResponse)
def get_artifacts(request: Request, session_id: str) -> SessionDetailResponse:
    store = request.app.state.store
    session = store.get_session(session_id)
    return SessionDetailResponse(session=session, artifacts=store.get_artifacts(session_id))
