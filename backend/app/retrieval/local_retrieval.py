"""Local evidence retrieval across parsed papers and prior session artifacts."""

from __future__ import annotations

from collections import Counter
from typing import Iterable

from backend.app.models.domain import AnalysisArtifact, EvidenceRef, ParsedDocument, QARecord, ReferenceAsset


def _tokenize(text: str) -> list[str]:
    return [token.lower() for token in text.replace("\n", " ").split() if len(token) > 2]


class LocalEvidenceRetriever:
    """Simple lexical retriever for session-local content."""

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
        scored: list[tuple[int, EvidenceRef]] = []

        for doc in parsed_docs:
            for section in doc.sections:
                score = self._score(query_tokens, f"{section.heading} {section.content}")
                if score:
                    scored.append(
                        (
                            score,
                            EvidenceRef(
                                source_type="paper",
                                asset_id=doc.paper_id,
                                label=f"{doc.title} — {section.heading}",
                                excerpt=section.content[:500],
                                locator=section.page_label,
                            ),
                        )
                    )

        for analysis in analyses:
            for section in analysis.sections:
                score = self._score(query_tokens, f"{section.title} {section.content}")
                if score:
                    scored.append(
                        (
                            score,
                            EvidenceRef(
                                source_type="paper",
                                asset_id=analysis.analysis_id,
                                label=f"{analysis.title} — {section.title}",
                                excerpt=section.content[:500],
                                locator=None,
                            ),
                        )
                    )

        for qa_record in qa_records:
            score = self._score(query_tokens, f"{qa_record.question_text} {qa_record.answer_text}")
            if score:
                scored.append(
                    (
                        score,
                        EvidenceRef(
                            source_type="reference",
                            asset_id=qa_record.question_id,
                            label="Previous QA record",
                            excerpt=qa_record.answer_text[:500],
                            locator=None,
                        ),
                    )
                )

        for reference in references:
            score = self._score(query_tokens, f"{reference.title} {reference.summary}")
            if score:
                scored.append(
                    (
                        score,
                        EvidenceRef(
                            source_type="reference",
                            asset_id=reference.reference_id,
                            label=reference.title,
                            excerpt=reference.summary[:500],
                            locator=reference.source_url,
                        ),
                    )
                )

        return [item for _, item in sorted(scored, key=lambda pair: pair[0], reverse=True)[:limit]]

    def _score(self, query_tokens: Counter[str], text: str) -> int:
        haystack = Counter(_tokenize(text))
        return sum(min(count, haystack[token]) for token, count in query_tokens.items())
