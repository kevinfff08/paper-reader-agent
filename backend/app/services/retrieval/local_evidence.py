"""Weighted local evidence retrieval across parsed papers and session artifacts."""

from __future__ import annotations

from collections import Counter
from typing import Iterable

from backend.app.core.models.domain import AnalysisArtifact, EvidenceRef, ParsedChunk, ParsedDocument, QARecord, ReferenceAsset


STOPWORDS = {
    "the",
    "and",
    "for",
    "that",
    "this",
    "with",
    "from",
    "are",
    "was",
    "were",
    "have",
    "has",
    "what",
    "which",
    "when",
    "where",
    "into",
    "about",
    "their",
    "they",
    "than",
}


def _tokenize(text: str) -> list[str]:
    cleaned = text.lower()
    for symbol in ",.;:!?()[]{}<>/\\|\"'`~@#$%^&*_+=-":
        cleaned = cleaned.replace(symbol, " ")
    return [token for token in cleaned.replace("\n", " ").split() if len(token) > 2 and token not in STOPWORDS]


class LocalEvidenceRetriever:
    """Weighted lexical retriever for session-local content."""

    def retrieve(
        self,
        query: str,
        *,
        parsed_docs: Iterable[ParsedDocument],
        analyses: Iterable[AnalysisArtifact],
        qa_records: Iterable[QARecord],
        references: Iterable[ReferenceAsset],
        limit: int = 6,
    ) -> list[EvidenceRef]:
        query_tokens = Counter(_tokenize(query))
        query_phrase = query.strip().lower()
        scored: list[tuple[float, EvidenceRef]] = []

        for doc in parsed_docs:
            for chunk in self._iter_chunks(doc):
                score = self._score(
                    query_tokens,
                    text=chunk.content,
                    heading=chunk.heading,
                    query_phrase=query_phrase,
                    source_weight=4.0,
                )
                if score <= 0:
                    continue
                scored.append(
                    (
                        score,
                        EvidenceRef(
                            source_type="paper",
                            asset_id=doc.paper_id,
                            label=f"{doc.title} - {chunk.heading}",
                            excerpt=chunk.content[:500],
                            locator=chunk.page_label or chunk.heading,
                            page_label=chunk.page_label,
                            score=score,
                        ),
                    )
                )

        for analysis in analyses:
            for section in analysis.sections:
                score = self._score(
                    query_tokens,
                    text=section.content,
                    heading=section.title,
                    query_phrase=query_phrase,
                    source_weight=3.0,
                )
                if score <= 0:
                    continue
                scored.append(
                    (
                        score,
                        EvidenceRef(
                            source_type="analysis",
                            asset_id=analysis.analysis_id,
                            label=f"{analysis.title} - {section.title}",
                            excerpt=section.content[:500],
                            locator=section.title,
                            score=score,
                        ),
                    )
                )

        for qa_record in qa_records:
            score = self._score(
                query_tokens,
                text=f"{qa_record.question_text} {qa_record.answer_text}",
                heading="Previous QA record",
                query_phrase=query_phrase,
                source_weight=1.0,
            )
            if score <= 0:
                continue
            scored.append(
                (
                    score,
                    EvidenceRef(
                        source_type="reference",
                        asset_id=qa_record.question_id,
                        label="Previous QA record",
                        excerpt=qa_record.answer_text[:500],
                        locator=None,
                        score=score,
                    ),
                )
            )

        for reference in references:
            score = self._score(
                query_tokens,
                text=reference.summary,
                heading=f"{reference.title} {reference.venue or ''}",
                query_phrase=query_phrase,
                source_weight=2.0,
            )
            if score <= 0:
                continue
            scored.append(
                (
                    score,
                    EvidenceRef(
                        source_type="reference",
                        asset_id=reference.reference_id,
                        label=reference.title,
                        excerpt=reference.summary[:500],
                        locator=reference.best_access_url or reference.source_url,
                        source_kind=reference.source_kind,
                        source_url=reference.best_access_url or reference.source_url,
                        score=score,
                    ),
                )
            )

        deduped: list[EvidenceRef] = []
        seen: set[tuple[str, str, str | None, str]] = set()
        for _, item in sorted(scored, key=lambda pair: pair[0], reverse=True):
            key = (item.source_type, item.asset_id, item.locator, item.excerpt[:80])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
            if len(deduped) >= limit:
                break
        return deduped

    def _score(
        self,
        query_tokens: Counter[str],
        *,
        text: str,
        heading: str,
        query_phrase: str,
        source_weight: float,
    ) -> float:
        haystack = Counter(_tokenize(text))
        heading_tokens = Counter(_tokenize(heading))
        token_score = sum(min(count, haystack[token]) for token, count in query_tokens.items())
        heading_score = sum(min(count, heading_tokens[token]) for token, count in query_tokens.items())
        phrase_bonus = 2.0 if query_phrase and query_phrase in f"{heading} {text}".lower() else 0.0
        return (token_score * source_weight) + (heading_score * (source_weight + 1.5)) + phrase_bonus

    def _iter_chunks(self, doc: ParsedDocument) -> list[ParsedChunk]:
        if doc.chunks:
            return list(doc.chunks)
        chunks: list[ParsedChunk] = []
        for section_index, section in enumerate(doc.sections):
            remaining = section.content.strip()
            chunk_index = 0
            while remaining:
                if len(remaining) <= 1200:
                    chunk_text = remaining
                    remaining = ""
                else:
                    split_at = remaining.rfind(" ", 0, 1200)
                    if split_at <= 0:
                        split_at = 1200
                    chunk_text = remaining[:split_at].strip()
                    remaining = remaining[split_at:].lstrip()
                chunks.append(
                    ParsedChunk(
                        chunk_id=f"lazy-{section_index + 1}-{chunk_index + 1}",
                        heading=section.heading,
                        content=chunk_text,
                        page_label=section.page_label,
                    )
                )
                chunk_index += 1
        return chunks
