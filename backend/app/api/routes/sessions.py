"""Session-centric REST routes."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from backend.app.core.models.api import (
    AnalysisResponse,
    AnalyzeSessionRequest,
    ArchiveResponse,
    ArchiveSessionRequest,
    AskQuestionRequest,
    CreateRunRequest,
    CreateTaskRequest,
    CreateSessionRequest,
    DiscoverLiteratureRequest,
    DiscoverLiteratureResponse,
    LiteratureSearchListResponse,
    LocalizeDiscoveryReferenceRequest,
    QuestionResponse,
    ReferenceResponse,
    RunResponse,
    SessionDetailResponse,
    SessionListResponse,
    TaskListResponse,
    TaskResponse,
)
from backend.app.core.models.domain import LiteratureSearchRecord, ReferenceAsset
from backend.app.services.discovery.search_broker import DiscoveryContext


router = APIRouter(tags=["sessions"])


def _resolve_analysis(request: Request, session_id: str, artifact_ref: str):
    analysis_id = artifact_ref.split(":", 1)[1]
    for analysis in request.app.state.store.list_analyses(session_id):
        if analysis.analysis_id == analysis_id:
            return analysis
    raise HTTPException(status_code=404, detail=f"Analysis artifact not found: {analysis_id}")


def _resolve_qa_record(request: Request, session_id: str, artifact_ref: str):
    question_id = artifact_ref.split(":", 1)[1]
    for record in request.app.state.store.list_qa_records(session_id):
        if record.question_id == question_id:
            return record
    raise HTTPException(status_code=404, detail=f"QA artifact not found: {question_id}")


def _build_localized_reference(request: Request, session_id: str, discovered_result) -> ReferenceAsset:
    store = request.app.state.store
    session_dir = store.session_dir(session_id)
    reference_id = uuid4().hex[:12]
    localized_path: str | None = None
    if discovered_result.summary:
        path = session_dir / "references" / f"{reference_id}.md"
        lines = [f"# {discovered_result.title}", ""]
        if discovered_result.best_access_url:
            lines.append(f"Best access: {discovered_result.best_access_url}")
            lines.append("")
        if discovered_result.landing_page_url:
            lines.append(f"Landing page: {discovered_result.landing_page_url}")
            lines.append("")
        if discovered_result.pdf_url:
            lines.append(f"PDF: {discovered_result.pdf_url}")
            lines.append("")
        lines.append(discovered_result.summary)
        path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
        localized_path = str(path)
    return ReferenceAsset(
        reference_id=reference_id,
        title=discovered_result.title,
        source_kind=discovered_result.source_kind,
        source_url=discovered_result.source_url,
        localized_path=localized_path,
        summary=discovered_result.summary,
        doi=discovered_result.doi,
        authors=discovered_result.authors,
        year=discovered_result.year,
        venue=discovered_result.venue,
        citation_count=discovered_result.citation_count,
        landing_page_url=discovered_result.landing_page_url,
        pdf_url=discovered_result.pdf_url,
        best_access_url=discovered_result.best_access_url,
        manual_search_url=discovered_result.manual_search_url,
        oa_status=discovered_result.oa_status,
        acquisition_status=(
            "localized_summary" if localized_path and discovered_result.summary else discovered_result.acquisition_status
        ),
        search_reason=discovered_result.search_reason,
        is_supplementary=discovered_result.is_supplementary,
        created_at=datetime.now(UTC),
    )


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


@router.post("/sessions/{session_id}/discover", response_model=DiscoverLiteratureResponse)
def discover_literature(
    request: Request,
    session_id: str,
    payload: DiscoverLiteratureRequest,
) -> DiscoverLiteratureResponse:
    store = request.app.state.store
    try:
        session = store.get_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    results = request.app.state.search_broker.discover(
        query=payload.query,
        discovery_mode=payload.discovery_mode,
        domain=payload.domain,
        max_results=payload.max_results,
        preferred_venues=payload.preferred_venues,
        session_context=DiscoveryContext(session=session, papers=store.list_papers(session_id)),
    )
    search = LiteratureSearchRecord(
        search_id=uuid4().hex[:12],
        session_id=session_id,
        query=payload.query,
        discovery_mode=payload.discovery_mode,  # type: ignore[arg-type]
        domain=payload.domain,  # type: ignore[arg-type]
        preferred_venues=payload.preferred_venues,
        results=results,
        created_at=datetime.now(UTC),
    )
    store.save_literature_search(session_id, search)
    return DiscoverLiteratureResponse(search=search)


@router.get("/sessions/{session_id}/discover", response_model=LiteratureSearchListResponse)
def list_discoveries(request: Request, session_id: str) -> LiteratureSearchListResponse:
    store = request.app.state.store
    try:
        store.get_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return LiteratureSearchListResponse(searches=store.list_literature_searches(session_id))


@router.get("/sessions/{session_id}/discover/{search_id}", response_model=DiscoverLiteratureResponse)
def get_discovery(request: Request, session_id: str, search_id: str) -> DiscoverLiteratureResponse:
    try:
        search = request.app.state.store.get_literature_search(session_id, search_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return DiscoverLiteratureResponse(search=search)


@router.post("/sessions/{session_id}/discover/{search_id}/localize", response_model=ReferenceResponse)
def localize_discovery_result(
    request: Request,
    session_id: str,
    search_id: str,
    payload: LocalizeDiscoveryReferenceRequest,
) -> ReferenceResponse:
    store = request.app.state.store
    try:
        search = store.get_literature_search(session_id, search_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    match = next((item for item in search.results if item.result_id == payload.result_id), None)
    if match is None:
        raise HTTPException(status_code=404, detail=f"Search result not found: {payload.result_id}")
    reference = _build_localized_reference(request, session_id, match)
    store.save_reference(session_id, reference)
    return ReferenceResponse(reference=reference)


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


@router.post("/sessions/{session_id}/runs", response_model=RunResponse)
def create_run(request: Request, session_id: str, payload: CreateRunRequest) -> RunResponse:
    try:
        request.app.state.store.get_session(session_id)
        run = request.app.state.run_engine.start_run(
            session_id,
            mode=payload.mode,
            input_text=payload.input,
            preferred_paper_ids=payload.preferred_paper_ids,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RunResponse(run=run)


@router.get("/sessions/{session_id}/runs/{run_id}", response_model=RunResponse)
def get_run(request: Request, session_id: str, run_id: str) -> RunResponse:
    try:
        run = request.app.state.store.get_run(session_id, run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RunResponse(run=run)


@router.get("/sessions/{session_id}/runs/{run_id}/events")
async def stream_run_events(request: Request, session_id: str, run_id: str) -> StreamingResponse:
    try:
        request.app.state.store.get_run(session_id, run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return StreamingResponse(
        request.app.state.run_engine.stream_events(session_id, run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/sessions/{session_id}/tasks", response_model=TaskResponse)
def create_task(request: Request, session_id: str, payload: CreateTaskRequest) -> TaskResponse:
    try:
        request.app.state.store.get_session(session_id)
        task = request.app.state.task_engine.start_task(
            session_id,
            agent_kind=payload.agent_kind,  # type: ignore[arg-type]
            input_text=payload.input,
            parent_run_id=payload.parent_run_id,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return TaskResponse(task=task)


@router.get("/sessions/{session_id}/tasks", response_model=TaskListResponse)
def list_tasks(request: Request, session_id: str) -> TaskListResponse:
    try:
        request.app.state.store.get_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return TaskListResponse(tasks=request.app.state.store.list_tasks(session_id))


@router.get("/sessions/{session_id}/tasks/{task_id}", response_model=TaskResponse)
def get_task(request: Request, session_id: str, task_id: str) -> TaskResponse:
    try:
        task = request.app.state.store.get_task(session_id, task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return TaskResponse(task=task)


@router.get("/sessions/{session_id}/tasks/{task_id}/events")
async def stream_task_events(request: Request, session_id: str, task_id: str) -> StreamingResponse:
    try:
        request.app.state.store.get_task(session_id, task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return StreamingResponse(
        request.app.state.task_engine.stream_events(session_id, task_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/sessions/{session_id}/tasks/{task_id}/stop", response_model=TaskResponse)
def stop_task(request: Request, session_id: str, task_id: str) -> TaskResponse:
    try:
        task = request.app.state.task_engine.stop_task(session_id, task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return TaskResponse(task=task)


@router.post("/sessions/{session_id}/analyze", response_model=AnalysisResponse)
def analyze_session(
    request: Request,
    session_id: str,
    payload: AnalyzeSessionRequest,
) -> AnalysisResponse:
    try:
        run = request.app.state.run_engine.run_sync(
            session_id,
            mode="analyze",
            input_text=payload.focus_question or "",
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not run.final_artifact_ref:
        raise HTTPException(status_code=500, detail="Analyze run did not produce an artifact")
    return AnalysisResponse(analysis=_resolve_analysis(request, session_id, run.final_artifact_ref))


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
    try:
        run = request.app.state.run_engine.run_sync(
            session_id,
            mode="answer",
            input_text=payload.question,
            preferred_paper_ids=payload.preferred_paper_ids,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not run.final_artifact_ref:
        raise HTTPException(status_code=500, detail="Answer run did not produce an artifact")
    return QuestionResponse(qa_record=_resolve_qa_record(request, session_id, run.final_artifact_ref))


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
    try:
        run = request.app.state.run_engine.run_sync(
            session_id,
            mode="archive",
            input_text="build archive",
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    archive = request.app.state.store.load_archive(session_id)
    if archive is None or not run.final_artifact_ref:
        raise HTTPException(status_code=500, detail="Archive run did not produce an artifact")
    return ArchiveResponse(archive=archive)


@router.get("/sessions/{session_id}/artifacts", response_model=SessionDetailResponse)
def get_artifacts(request: Request, session_id: str) -> SessionDetailResponse:
    store = request.app.state.store
    session = store.get_session(session_id)
    return SessionDetailResponse(session=session, artifacts=store.get_artifacts(session_id))
