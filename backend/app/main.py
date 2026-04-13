"""FastAPI entry point for PaperReader."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.routes.sessions import router as session_router
from backend.app.core.config import get_settings
from backend.app.llm.client import LLMClient
from backend.app.runtime.run_engine import RunEngine
from backend.app.runtime.task_engine import TaskEngine
from backend.app.services.discovery.external_retrieval import ExternalRetriever
from backend.app.services.discovery.search_broker import SearchBroker
from backend.app.services.parsing.document_parser import DocumentParser
from backend.app.services.reporting.archive_report import ArchiveReportBuilder
from backend.app.services.retrieval.local_evidence import LocalEvidenceRetriever
from backend.app.services.verification.verifier import AnswerVerifier
from backend.app.storage.session_store import SessionStore


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()
    store = SessionStore(settings.session_data_root, test_mode=settings.test_mode)
    llm_client = LLMClient(
        provider=settings.llm_provider,
        mode=settings.llm_mode,
        api_key=settings.openai_api_key if settings.llm_provider == "openai" else settings.claude_api_key,
        model=settings.llm_model,
        base_url=settings.llm_proxy_url,
    )
    search_broker = SearchBroker(
        openalex_email=settings.openalex_email,
        tavily_api_key=settings.tavily_api_key,
    )
    run_engine = RunEngine(
        task_engine=TaskEngine(store=store, llm_client=llm_client, verifier=AnswerVerifier()),
        store=store,
        parser=DocumentParser(max_chars=settings.max_parse_chars),
        llm_client=llm_client,
        local_retriever=LocalEvidenceRetriever(),
        external_retriever=ExternalRetriever(
            semantic_scholar_api_key=settings.semantic_scholar_api_key,
            openalex_email=settings.openalex_email,
            tavily_api_key=settings.tavily_api_key,
            search_broker=search_broker,
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
    app.state.search_broker = search_broker
    app.state.run_engine = run_engine
    app.state.task_engine = run_engine.task_engine
    app.include_router(session_router)

    @app.get("/healthz")
    def healthcheck() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
