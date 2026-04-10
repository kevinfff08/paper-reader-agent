"""FastAPI entry point for PaperReader."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.routes.sessions import router as session_router
from backend.app.config import get_settings
from backend.app.llm.client import LLMClient
from backend.app.orchestrator.study_orchestrator import StudyOrchestrator
from backend.app.parsers.document_parser import DocumentParser
from backend.app.reports.archive_report import ArchiveReportBuilder
from backend.app.retrieval.external_retrieval import ExternalRetriever
from backend.app.retrieval.local_retrieval import LocalEvidenceRetriever
from backend.app.storage.session_store import SessionStore
from backend.app.verification.verifier import AnswerVerifier


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()
    store = SessionStore(settings.session_data_root)
    llm_client = LLMClient(
        provider=settings.llm_provider,
        mode=settings.llm_mode,
        api_key=settings.openai_api_key if settings.llm_provider == "openai" else settings.claude_api_key,
        model=settings.llm_model,
        base_url=settings.llm_proxy_url,
    )
    orchestrator = StudyOrchestrator(
        store=store,
        parser=DocumentParser(max_chars=settings.max_parse_chars),
        llm_client=llm_client,
        local_retriever=LocalEvidenceRetriever(),
        external_retriever=ExternalRetriever(
            semantic_scholar_api_key=settings.semantic_scholar_api_key,
            openalex_email=settings.openalex_email,
            tavily_api_key=settings.tavily_api_key,
        ),
        verifier=AnswerVerifier(),
        archive_builder=ArchiveReportBuilder(),
    )

    app = FastAPI(title="PaperReader API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.settings = settings
    app.state.store = store
    app.state.orchestrator = orchestrator
    app.include_router(session_router)

    @app.get("/healthz")
    def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
