"""External retrieval helpers with an academic-first search policy."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from backend.app.logging.session_logger import get_app_logger


logger = get_app_logger("external_retrieval")


@dataclass(slots=True)
class ExternalSearchItem:
    """One search result ready to localize into the session."""

    title: str
    source_kind: str
    source_url: str
    summary: str


class ExternalRetriever:
    """Fetch lightweight references with scholarly indexes ahead of web search."""

    def __init__(
        self,
        *,
        semantic_scholar_api_key: str | None = None,
        openalex_email: str | None = None,
        tavily_api_key: str | None = None,
    ):
        self.semantic_scholar_api_key = semantic_scholar_api_key
        self.openalex_email = openalex_email
        self.tavily_api_key = tavily_api_key

    def search(self, query: str, limit: int = 3) -> list[ExternalSearchItem]:
        """Search configured sources in priority order.

        The order is intentionally conservative for paper-reading workflows:
        Semantic Scholar first, then OpenAlex, and only then supplemental web
        search. This keeps answers grounded in academic sources whenever
        possible.
        """
        results: list[ExternalSearchItem] = []
        results.extend(self._search_semantic_scholar(query, limit))
        if len(results) < limit:
            results.extend(self._search_openalex(query, limit - len(results)))
        if len(results) < limit:
            results.extend(self._search_tavily(query, limit - len(results)))
        return results[:limit]

    def _search_semantic_scholar(self, query: str, limit: int) -> list[ExternalSearchItem]:
        headers = {"Accept": "application/json"}
        if self.semantic_scholar_api_key:
            headers["x-api-key"] = self.semantic_scholar_api_key
        try:
            with httpx.Client(timeout=20.0) as client:
                response = client.get(
                    "https://api.semanticscholar.org/graph/v1/paper/search",
                    headers=headers,
                    params={"query": query, "limit": limit, "fields": "title,abstract,url"},
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            logger.info("Semantic Scholar search skipped: %s", exc)
            return []
        items = payload.get("data", [])
        return [
            ExternalSearchItem(
                title=item.get("title") or "Untitled",
                source_kind="semantic_scholar",
                source_url=item.get("url") or "",
                summary=(item.get("abstract") or "")[:1200],
            )
            for item in items
        ]

    def _search_openalex(self, query: str, limit: int) -> list[ExternalSearchItem]:
        headers = {}
        if self.openalex_email:
            headers["User-Agent"] = f"PaperReader ({self.openalex_email})"
        try:
            with httpx.Client(timeout=20.0, headers=headers) as client:
                response = client.get(
                    "https://api.openalex.org/works",
                    params={"search": query, "per-page": limit},
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            logger.info("OpenAlex search skipped: %s", exc)
            return []
        items = payload.get("results", [])
        return [
            ExternalSearchItem(
                title=item.get("display_name") or "Untitled",
                source_kind="openalex",
                source_url=item.get("id") or "",
                summary=(item.get("abstract_inverted_index") and "OpenAlex abstract index available") or "",
            )
            for item in items
        ]

    def _search_tavily(self, query: str, limit: int) -> list[ExternalSearchItem]:
        if not self.tavily_api_key:
            return []
        try:
            with httpx.Client(timeout=20.0) as client:
                response = client.post(
                    "https://api.tavily.com/search",
                    json={"api_key": self.tavily_api_key, "query": query, "max_results": limit},
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            logger.info("Tavily search skipped: %s", exc)
            return []
        return [
            ExternalSearchItem(
                title=item.get("title") or "Untitled",
                source_kind="web",
                source_url=item.get("url") or "",
                summary=(item.get("content") or "")[:1200],
            )
            for item in payload.get("results", [])
        ]
