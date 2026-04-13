"""Literature discovery broker and provider adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Iterable
from urllib.parse import quote_plus
from uuid import uuid4

import httpx

from backend.app.core.models.domain import (
    AcquisitionStatus,
    DiscoveryDomain,
    DiscoveryMode,
    DiscoveredPaper,
    PaperAsset,
    ReferenceSourceKind,
    SessionSummary,
)
from backend.app.logging.session_logger import get_app_logger


logger = get_app_logger("search_broker")


CS_VENUE_KEYWORDS = {
    "neurips",
    "icml",
    "iclr",
    "acl",
    "emnlp",
    "naacl",
    "cvpr",
    "iccv",
    "eccv",
    "kdd",
    "www",
    "sigir",
}
BIOMED_VENUE_KEYWORDS = {"nature", "science", "cell", "nejm", "lancet", "jama", "bmj"}


@dataclass(slots=True)
class DiscoveryContext:
    """Session-local information useful for related-work expansion."""

    session: SessionSummary
    papers: list[PaperAsset]


class WebSearchProvider:
    """Supplemental web search via Tavily."""

    def __init__(self, api_key: str | None):
        self.api_key = api_key

    def search(
        self,
        query: str,
        *,
        limit: int,
        source_kind: ReferenceSourceKind = "web",
        include_domains: list[str] | None = None,
        is_supplementary: bool = True,
    ) -> list[DiscoveredPaper]:
        if not self.api_key:
            return []
        body: dict[str, object] = {
            "api_key": self.api_key,
            "query": query,
            "max_results": limit,
            "search_depth": "advanced",
        }
        if include_domains:
            body["include_domains"] = include_domains
        try:
            with httpx.Client(timeout=20.0) as client:
                response = client.post("https://api.tavily.com/search", json=body)
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            logger.info("Web search skipped: %s", exc)
            return []
        results: list[DiscoveredPaper] = []
        for item in payload.get("results", []):
            url = item.get("url") or ""
            results.append(
                DiscoveredPaper(
                    result_id=uuid4().hex[:12],
                    title=item.get("title") or "Untitled",
                    source_kind=source_kind,
                    source_url=url,
                    summary=(item.get("content") or "")[:1200],
                    landing_page_url=url or None,
                    best_access_url=url or None,
                    manual_search_url=_manual_search_url(query, include_domains),
                    oa_status="unknown",
                    acquisition_status="remote_landing_only",
                    search_reason="supplementary web search",
                    is_supplementary=is_supplementary,
                )
            )
        return results


class OpenAlexProvider:
    """Primary open scholarly-graph provider."""

    def __init__(self, email: str | None):
        self.email = email

    def search(
        self,
        query: str,
        *,
        limit: int,
        sort: str | None = None,
        filter_expr: str | None = None,
    ) -> list[DiscoveredPaper]:
        headers = {}
        if self.email:
            headers["User-Agent"] = f"PaperReader ({self.email})"
        params: dict[str, object] = {"search": query, "per-page": limit}
        if sort:
            params["sort"] = sort
        if filter_expr:
            params["filter"] = filter_expr
        try:
            with httpx.Client(timeout=20.0, headers=headers) as client:
                response = client.get("https://api.openalex.org/works", params=params)
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            logger.info("OpenAlex search skipped: %s", exc)
            return []
        return [self._to_result(item) for item in payload.get("results", [])]

    def lookup_open_access(self, doi: str) -> dict[str, str | None]:
        if not doi:
            return {}
        results = self.search(doi, limit=1)
        if not results:
            return {}
        item = results[0]
        return {
            "landing_page_url": item.landing_page_url,
            "pdf_url": item.pdf_url,
            "best_access_url": item.best_access_url,
        }

    def _to_result(self, item: dict) -> DiscoveredPaper:
        doi = item.get("doi")
        authors = [
            authorship.get("author", {}).get("display_name")
            for authorship in item.get("authorships", [])
            if authorship.get("author", {}).get("display_name")
        ]
        venue = (
            item.get("primary_location", {})
            .get("source", {})
            .get("display_name")
        )
        landing_page_url = (
            item.get("best_oa_location", {}) or item.get("primary_location", {}) or {}
        ).get("landing_page_url")
        pdf_url = (
            item.get("best_oa_location", {}) or item.get("primary_location", {}) or {}
        ).get("pdf_url")
        summary = _abstract_from_inverted_index(item.get("abstract_inverted_index", {}))
        return DiscoveredPaper(
            result_id=uuid4().hex[:12],
            title=item.get("display_name") or "Untitled",
            authors=authors,
            year=item.get("publication_year"),
            venue=venue,
            source_kind="openalex",
            source_url=landing_page_url or item.get("id") or "",
            doi=doi,
            citation_count=item.get("cited_by_count"),
            summary=summary[:1200],
            landing_page_url=landing_page_url,
            pdf_url=pdf_url,
            best_access_url=pdf_url or landing_page_url or doi,
            manual_search_url=_manual_search_url(item.get("display_name") or ""),
            oa_status="open" if item.get("open_access", {}).get("is_oa") else "closed",
            acquisition_status=_access_status(pdf_url=pdf_url, landing_page_url=landing_page_url),
            search_reason="openalex scholarly graph",
            is_supplementary=False,
        )


class CrossrefProvider:
    """Metadata enrichment and seminal-paper support."""

    def search(self, query: str, *, limit: int, seminal: bool = False) -> list[DiscoveredPaper]:
        params: dict[str, object] = {"rows": limit, "query.bibliographic": query}
        if seminal:
            params["sort"] = "is-referenced-by-count"
            params["order"] = "desc"
        try:
            with httpx.Client(timeout=20.0) as client:
                response = client.get("https://api.crossref.org/works", params=params)
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            logger.info("Crossref search skipped: %s", exc)
            return []
        return [self._to_result(item) for item in payload.get("message", {}).get("items", [])]

    def _to_result(self, item: dict) -> DiscoveredPaper:
        doi = item.get("DOI")
        title_list = item.get("title") or []
        title = title_list[0] if title_list else "Untitled"
        venue = None
        for key in ("container-title", "short-container-title"):
            values = item.get(key) or []
            if values:
                venue = values[0]
                break
        year = None
        parts = (
            item.get("published-print", {}).get("date-parts")
            or item.get("published-online", {}).get("date-parts")
            or item.get("created", {}).get("date-parts")
            or []
        )
        if parts and parts[0]:
            year = parts[0][0]
        authors = []
        for author in item.get("author", []):
            name = " ".join(part for part in (author.get("given"), author.get("family")) if part)
            if name:
                authors.append(name)
        landing = f"https://doi.org/{doi}" if doi else (item.get("URL") or "")
        return DiscoveredPaper(
            result_id=uuid4().hex[:12],
            title=title,
            authors=authors,
            year=year,
            venue=venue,
            source_kind="crossref",
            source_url=landing,
            doi=doi,
            citation_count=item.get("is-referenced-by-count"),
            summary="",
            landing_page_url=landing or None,
            best_access_url=landing or None,
            manual_search_url=_manual_search_url(title),
            oa_status="unknown",
            acquisition_status=_access_status(pdf_url=None, landing_page_url=landing or None),
            search_reason="crossref metadata",
            is_supplementary=False,
        )


class EuropePmcProvider:
    """Biomedical literature search and OA discovery."""

    def search(self, query: str, *, limit: int) -> list[DiscoveredPaper]:
        params = {"query": query, "format": "json", "pageSize": limit}
        try:
            with httpx.Client(timeout=20.0) as client:
                response = client.get("https://www.ebi.ac.uk/europepmc/webservices/rest/search", params=params)
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            logger.info("Europe PMC search skipped: %s", exc)
            return []
        items = payload.get("resultList", {}).get("result", [])
        results: list[DiscoveredPaper] = []
        for item in items:
            doi = item.get("doi")
            pmcid = item.get("pmcid")
            landing = (
                f"https://europepmc.org/article/MED/{item.get('id')}"
                if item.get("id")
                else (f"https://europepmc.org/article/PMC/{pmcid}" if pmcid else "")
            )
            pdf = f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/pdf/" if pmcid else None
            results.append(
                DiscoveredPaper(
                    result_id=uuid4().hex[:12],
                    title=item.get("title") or "Untitled",
                    authors=[item.get("authorString")] if item.get("authorString") else [],
                    year=_safe_int(item.get("pubYear")),
                    venue=item.get("journalTitle"),
                    source_kind="europe_pmc",
                    source_url=landing,
                    doi=doi,
                    citation_count=_safe_int(item.get("citedByCount")),
                    summary=(item.get("abstractText") or "")[:1200],
                    landing_page_url=landing or None,
                    pdf_url=pdf,
                    best_access_url=pdf or landing or (f"https://doi.org/{doi}" if doi else None),
                    manual_search_url=_manual_search_url(item.get("title") or ""),
                    oa_status="open" if pmcid else "unknown",
                    acquisition_status=_access_status(pdf_url=pdf, landing_page_url=landing or None),
                    search_reason="Europe PMC biomedical index",
                    is_supplementary=False,
                )
            )
        return results

    def lookup_by_doi(self, doi: str) -> dict[str, str | None]:
        if not doi:
            return {}
        results = self.search(f'DOI:"{doi}"', limit=1)
        if not results:
            return {}
        item = results[0]
        return {
            "landing_page_url": item.landing_page_url,
            "pdf_url": item.pdf_url,
            "best_access_url": item.best_access_url,
        }


class PubmedProvider:
    """PubMed metadata search."""

    def search(self, query: str, *, limit: int) -> list[DiscoveredPaper]:
        try:
            with httpx.Client(timeout=20.0) as client:
                ids_response = client.get(
                    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
                    params={
                        "db": "pubmed",
                        "term": query,
                        "retmode": "json",
                        "retmax": limit,
                        "sort": "relevance",
                    },
                )
                ids_response.raise_for_status()
                id_payload = ids_response.json()
                ids = id_payload.get("esearchresult", {}).get("idlist", [])
                if not ids:
                    return []
                summary_response = client.get(
                    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
                    params={"db": "pubmed", "id": ",".join(ids), "retmode": "json"},
                )
                summary_response.raise_for_status()
                payload = summary_response.json()
        except Exception as exc:
            logger.info("PubMed search skipped: %s", exc)
            return []
        results: list[DiscoveredPaper] = []
        for identifier in ids:
            item = payload.get("result", {}).get(identifier, {})
            title = item.get("title")
            if not title:
                continue
            authors = [author.get("name") for author in item.get("authors", []) if author.get("name")]
            landing = f"https://pubmed.ncbi.nlm.nih.gov/{identifier}/"
            results.append(
                DiscoveredPaper(
                    result_id=uuid4().hex[:12],
                    title=title,
                    authors=authors,
                    year=_safe_int((item.get("pubdate") or "")[:4]),
                    venue=item.get("fulljournalname"),
                    source_kind="pubmed",
                    source_url=landing,
                    citation_count=None,
                    summary="",
                    landing_page_url=landing,
                    best_access_url=landing,
                    manual_search_url=_manual_search_url(title),
                    oa_status="unknown",
                    acquisition_status="remote_landing_only",
                    search_reason="PubMed biomedical metadata",
                    is_supplementary=False,
                )
            )
        return results


class DomainSiteSearchProvider:
    """Official-site fallback powered by the supplemental web search provider."""

    def __init__(self, web_provider: WebSearchProvider, domain: str, source_kind: ReferenceSourceKind):
        self.web_provider = web_provider
        self.domain = domain
        self.source_kind = source_kind

    def search(self, query: str, *, limit: int) -> list[DiscoveredPaper]:
        return self.web_provider.search(
            query,
            limit=limit,
            source_kind=self.source_kind,
            include_domains=[self.domain],
            is_supplementary=False,
        )


class SearchBroker:
    """Coordinate literature discovery across multiple providers."""

    def __init__(self, *, openalex_email: str | None = None, tavily_api_key: str | None = None):
        self.openalex = OpenAlexProvider(openalex_email)
        self.crossref = CrossrefProvider()
        self.europe_pmc = EuropePmcProvider()
        self.pubmed = PubmedProvider()
        self.web = WebSearchProvider(tavily_api_key)
        self.openreview = DomainSiteSearchProvider(self.web, "openreview.net", "openreview")
        self.acl = DomainSiteSearchProvider(self.web, "aclanthology.org", "acl")
        self.cvf = DomainSiteSearchProvider(self.web, "openaccess.thecvf.com", "cvf")
        self.pmlr = DomainSiteSearchProvider(self.web, "proceedings.mlr.press", "pmlr")
        self.openalex_email = openalex_email

    def discover(
        self,
        *,
        query: str,
        discovery_mode: DiscoveryMode,
        domain: DiscoveryDomain,
        max_results: int,
        preferred_venues: list[str] | None = None,
        session_context: DiscoveryContext | None = None,
    ) -> list[DiscoveredPaper]:
        preferred_venues = preferred_venues or []
        if discovery_mode == "latest_top_venues":
            results = self._discover_latest(query, domain=domain, max_results=max_results, preferred_venues=preferred_venues)
        elif discovery_mode == "seminal":
            results = self._discover_seminal(query, domain=domain, max_results=max_results, preferred_venues=preferred_venues)
        elif discovery_mode == "related":
            related_query = self._build_related_query(query, session_context)
            results = self._discover_related(related_query, domain=domain, max_results=max_results, preferred_venues=preferred_venues)
        else:
            results = self.search_supporting_context(query, limit=max_results)
        return self._finalize_results(results, query=query, limit=max_results, discovery_mode=discovery_mode, preferred_venues=preferred_venues)

    def search_supporting_context(self, query: str, limit: int = 3) -> list[DiscoveredPaper]:
        results = []
        results.extend(self.openalex.search(query, limit=limit))
        if len(results) < limit:
            results.extend(self.crossref.search(query, limit=limit - len(results)))
        if len(results) < limit:
            results.extend(self.web.search(query, limit=limit - len(results), source_kind="web", is_supplementary=True))
        return self._finalize_results(results, query=query, limit=limit, discovery_mode="supporting_context", preferred_venues=[])

    def _discover_latest(
        self,
        query: str,
        *,
        domain: DiscoveryDomain,
        max_results: int,
        preferred_venues: list[str],
    ) -> list[DiscoveredPaper]:
        results: list[DiscoveredPaper] = []
        if domain == "cs":
            per_provider = max(2, max_results // 4)
            results.extend(self.openreview.search(query, limit=per_provider))
            results.extend(self.acl.search(query, limit=per_provider))
            results.extend(self.cvf.search(query, limit=per_provider))
            results.extend(self.pmlr.search(query, limit=per_provider))
            results.extend(self.openalex.search(query, limit=max_results, sort="publication_date:desc"))
        elif domain == "biomed":
            results.extend(self.pubmed.search(query, limit=max_results))
            results.extend(self.europe_pmc.search(query, limit=max_results))
            results.extend(self.openalex.search(query, limit=max_results, sort="publication_date:desc"))
        else:
            results.extend(self.openalex.search(query, limit=max_results, sort="publication_date:desc"))
            results.extend(self.crossref.search(query, limit=max_results))
        return results

    def _discover_seminal(
        self,
        query: str,
        *,
        domain: DiscoveryDomain,
        max_results: int,
        preferred_venues: list[str],
    ) -> list[DiscoveredPaper]:
        del domain, preferred_venues
        results: list[DiscoveredPaper] = []
        results.extend(self.openalex.search(query, limit=max_results, sort="cited_by_count:desc"))
        results.extend(self.crossref.search(query, limit=max_results, seminal=True))
        review_hits = self.web.search(
            f"{query} review survey seminal paper",
            limit=max(2, max_results // 3),
            source_kind="web",
            is_supplementary=True,
        )
        for item in review_hits:
            item.search_reason = "review/survey boost"
        results.extend(review_hits)
        return results

    def _discover_related(
        self,
        query: str,
        *,
        domain: DiscoveryDomain,
        max_results: int,
        preferred_venues: list[str],
    ) -> list[DiscoveredPaper]:
        del domain, preferred_venues
        results: list[DiscoveredPaper] = []
        results.extend(self.openalex.search(query, limit=max_results))
        results.extend(self.crossref.search(query, limit=max(3, max_results // 2)))
        return results

    def _build_related_query(self, query: str, session_context: DiscoveryContext | None) -> str:
        if session_context is None:
            return query
        paper_titles = [paper.title for paper in session_context.papers if paper.title][:2]
        context_parts = [query, *paper_titles, *session_context.session.categories[:2]]
        return " ".join(part for part in context_parts if part)

    def _finalize_results(
        self,
        results: list[DiscoveredPaper],
        *,
        query: str,
        limit: int,
        discovery_mode: DiscoveryMode,
        preferred_venues: list[str],
    ) -> list[DiscoveredPaper]:
        deduped = self._dedupe(results)
        venue_hints = {value.lower() for value in preferred_venues}
        if discovery_mode == "latest_top_venues":
            sorted_results = sorted(
                deduped,
                key=lambda item: (
                    self._venue_score(item, venue_hints),
                    item.year or 0,
                    self._access_score(item.acquisition_status),
                    item.citation_count or 0,
                ),
                reverse=True,
            )
        elif discovery_mode == "seminal":
            sorted_results = sorted(
                deduped,
                key=lambda item: (
                    self._venue_score(item, venue_hints),
                    item.citation_count or 0,
                    item.year or 0,
                    self._access_score(item.acquisition_status),
                ),
                reverse=True,
            )
        else:
            sorted_results = sorted(
                deduped,
                key=lambda item: (
                    item.citation_count or 0,
                    self._access_score(item.acquisition_status),
                    item.year or 0,
                ),
                reverse=True,
            )
        finalized = [self._apply_access_fallbacks(item, query) for item in sorted_results[:limit]]
        return finalized

    def _apply_access_fallbacks(self, item: DiscoveredPaper, query: str) -> DiscoveredPaper:
        updates: dict[str, object] = {
            "manual_search_url": item.manual_search_url or _manual_search_url(query),
        }
        if item.best_access_url or item.pdf_url or item.landing_page_url:
            return item.model_copy(update=updates)

        fallback = self.openalex.lookup_open_access(item.doi or "")
        if not fallback:
            fallback = self._lookup_unpaywall(item.doi or "")
        if not fallback:
            fallback = self.europe_pmc.lookup_by_doi(item.doi or "")

        landing = fallback.get("landing_page_url") if fallback else None
        pdf = fallback.get("pdf_url") if fallback else None
        best_access = fallback.get("best_access_url") if fallback else None
        if not best_access and item.doi:
            best_access = f"https://doi.org/{item.doi}"
        updates.update(
            {
                "landing_page_url": landing or item.landing_page_url,
                "pdf_url": pdf or item.pdf_url,
                "best_access_url": best_access or item.best_access_url,
                "acquisition_status": _access_status(pdf_url=pdf or item.pdf_url, landing_page_url=landing or item.landing_page_url),
                "oa_status": "open" if (pdf or item.pdf_url) else item.oa_status,
            }
        )
        return item.model_copy(update=updates)

    def _lookup_unpaywall(self, doi: str) -> dict[str, str | None]:
        if not doi or not self.openalex_email:
            return {}
        try:
            with httpx.Client(timeout=20.0) as client:
                response = client.get(
                    f"https://api.unpaywall.org/v2/{quote_plus(doi)}",
                    params={"email": self.openalex_email},
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            logger.info("Unpaywall lookup skipped: %s", exc)
            return {}
        best_location = payload.get("best_oa_location") or {}
        landing = best_location.get("landing_page_url")
        pdf = best_location.get("url_for_pdf") or best_location.get("pdf_url")
        best_access = pdf or landing or (f"https://doi.org/{doi}" if doi else None)
        return {
            "landing_page_url": landing,
            "pdf_url": pdf,
            "best_access_url": best_access,
        }

    def _dedupe(self, results: Iterable[DiscoveredPaper]) -> list[DiscoveredPaper]:
        deduped: list[DiscoveredPaper] = []
        seen: set[str] = set()
        for item in results:
            key = (item.doi or item.title).strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    def _venue_score(self, item: DiscoveredPaper, preferred_venues: set[str]) -> int:
        venue = (item.venue or "").lower()
        title = item.title.lower()
        score = 0
        if preferred_venues and any(token in venue for token in preferred_venues):
            score += 100
        if any(token in venue for token in CS_VENUE_KEYWORDS) or any(token in title for token in CS_VENUE_KEYWORDS):
            score += 50
        if any(token in venue for token in BIOMED_VENUE_KEYWORDS):
            score += 40
        if item.source_kind in {"openreview", "acl", "cvf", "pmlr", "pubmed", "europe_pmc"}:
            score += 20
        if "review" in title or "survey" in title:
            score += 10
        return score

    def _access_score(self, status: AcquisitionStatus) -> int:
        order = {
            "localized_fulltext": 5,
            "localized_summary": 4,
            "remote_pdf": 3,
            "remote_landing_only": 2,
            "metadata_only": 1,
        }
        return order.get(status, 0)


def _abstract_from_inverted_index(inverted_index: dict) -> str:
    if not inverted_index:
        return ""
    positions: dict[int, str] = {}
    for token, locations in inverted_index.items():
        for index in locations:
            positions[index] = token
    return " ".join(positions[index] for index in sorted(positions))


def _access_status(pdf_url: str | None, landing_page_url: str | None) -> AcquisitionStatus:
    if pdf_url:
        return "remote_pdf"
    if landing_page_url:
        return "remote_landing_only"
    return "metadata_only"


def _manual_search_url(query: str, include_domains: list[str] | None = None) -> str:
    suffix = ""
    if include_domains:
        suffix = " " + " ".join(f"site:{domain}" for domain in include_domains)
    return f"https://www.google.com/search?q={quote_plus((query + suffix).strip())}"


def _safe_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
