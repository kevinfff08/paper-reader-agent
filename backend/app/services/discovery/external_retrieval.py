"""Compatibility wrapper around the literature discovery broker."""

from __future__ import annotations

from dataclasses import dataclass

from backend.app.services.discovery.search_broker import SearchBroker


@dataclass(slots=True)
class ExternalSearchItem:
    """One search result ready to localize into the session."""

    title: str
    source_kind: str
    source_url: str
    summary: str


class ExternalRetriever:
    """Fetch lightweight references with scholarly discovery ahead of web search."""

    def __init__(
        self,
        *,
        semantic_scholar_api_key: str | None = None,
        openalex_email: str | None = None,
        tavily_api_key: str | None = None,
        search_broker: SearchBroker | None = None,
    ):
        del semantic_scholar_api_key
        self.search_broker = search_broker or SearchBroker(
            openalex_email=openalex_email,
            tavily_api_key=tavily_api_key,
        )

    def search(self, query: str, limit: int = 3) -> list[ExternalSearchItem]:
        """Search supporting context for question answering."""
        results = self.search_broker.search_supporting_context(query, limit=limit)
        return [
            ExternalSearchItem(
                title=item.title,
                source_kind=item.source_kind,
                source_url=item.best_access_url or item.landing_page_url or item.source_url,
                summary=item.summary,
            )
            for item in results[:limit]
        ]
