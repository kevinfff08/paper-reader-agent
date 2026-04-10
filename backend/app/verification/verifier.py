"""Simple verification policy for question answering."""

from __future__ import annotations

from backend.app.models.domain import EvidenceRef, VerificationStatus


class AnswerVerifier:
    """Apply a conservative verification label to an answer."""

    def verify(self, *, evidence_refs: list[EvidenceRef], used_external_sources: bool) -> VerificationStatus:
        """Return a coarse verification status."""
        if not evidence_refs:
            return "unverified"
        if used_external_sources:
            return "verified_external"
        return "verified_local"
