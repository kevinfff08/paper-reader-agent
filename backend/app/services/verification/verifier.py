"""Simple verification policy for question answering."""

from __future__ import annotations

from backend.app.core.models.domain import EvidenceRef, VerificationStatus


class AnswerVerifier:
    """Apply a conservative verification label to an answer."""

    def verify(self, *, evidence_refs: list[EvidenceRef], used_external_sources: bool) -> VerificationStatus:
        """Return a coarse verification status."""
        if any(item.source_type == "paper" for item in evidence_refs):
            return "verified_uploaded_paper"
        if evidence_refs and used_external_sources:
            return "supplemented_external"
        if evidence_refs:
            return "verified_session_local"
        if used_external_sources:
            return "links_only"
        if not evidence_refs:
            return "unverified"
        return "unverified"
