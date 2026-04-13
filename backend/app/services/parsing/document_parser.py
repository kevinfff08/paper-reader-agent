"""Local document parser with PDF-first fallback behavior."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from backend.app.core.models.domain import ParsedChunk, ParsedDocument, ParsedSection


class DocumentParser:
    """Parse local files into a lightweight structured representation."""

    def __init__(self, max_chars: int = 120000):
        self.max_chars = max_chars

    def parse(self, paper_id: str, file_path: Path) -> ParsedDocument:
        """Parse a paper file into a structured document."""
        text = self._extract_text(file_path)[: self.max_chars]
        title = self._guess_title(file_path, text)
        abstract = self._guess_abstract(text)
        sections = self._split_sections(text)
        if not sections:
            sections = [ParsedSection(heading="Document Body", content=text[:4000], page_label=None)]
        chunks = self._build_chunks(sections)
        return ParsedDocument(
            paper_id=paper_id,
            source_path=str(file_path),
            title=title,
            abstract=abstract,
            sections=sections,
            chunks=chunks,
            plain_text=text,
            created_at=datetime.now(UTC),
        )

    def _extract_text(self, file_path: Path) -> str:
        suffix = file_path.suffix.lower()
        if suffix == ".pdf":
            pdf_text = self._extract_pdf_text(file_path)
            if pdf_text.strip():
                return pdf_text
        try:
            return file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return file_path.read_text(encoding="utf-8", errors="ignore")

    def _extract_pdf_text(self, file_path: Path) -> str:
        try:
            import fitz  # type: ignore

            doc = fitz.open(file_path)
            return "\n".join(page.get_text("text") for page in doc)
        except Exception:
            pass
        try:
            from pypdf import PdfReader  # type: ignore

            reader = PdfReader(str(file_path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception:
            return ""

    def _guess_title(self, file_path: Path, text: str) -> str:
        first_nonempty = next((line.strip() for line in text.splitlines() if line.strip()), "")
        if first_nonempty:
            return first_nonempty[:160]
        return file_path.stem

    def _guess_abstract(self, text: str) -> str:
        match = re.search(r"(?is)\babstract\b[:\s]*(.+?)(?:\n\s*\n|\b1\b|\bintroduction\b)", text)
        if match:
            return match.group(1).strip()[:2000]
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        return paragraphs[0][:2000] if paragraphs else ""

    def _split_sections(self, text: str) -> list[ParsedSection]:
        heading_pattern = re.compile(r"(?m)^(?:\d+(?:\.\d+)*)?\s*(Introduction|Background|Related Work|Method|Methods|Approach|Experiments|Results|Discussion|Conclusion|Limitations)\b.*$")
        matches = list(heading_pattern.finditer(text))
        if not matches:
            paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
            return [
                ParsedSection(heading=f"Section {index + 1}", content=paragraph[:3000], page_label=None)
                for index, paragraph in enumerate(paragraphs[:8])
            ]

        sections: list[ParsedSection] = []
        for index, match in enumerate(matches):
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            heading = match.group(0).strip()
            content = text[start:end].strip()
            sections.append(ParsedSection(heading=heading, content=content[:5000], page_label=None))
        return sections

    def _build_chunks(self, sections: list[ParsedSection], chunk_size: int = 1200) -> list[ParsedChunk]:
        chunks: list[ParsedChunk] = []
        for section_index, section in enumerate(sections):
            remaining = section.content.strip()
            chunk_index = 0
            while remaining:
                if len(remaining) <= chunk_size:
                    chunk_text = remaining
                    remaining = ""
                else:
                    split_at = remaining.rfind(" ", 0, chunk_size)
                    if split_at <= 0:
                        split_at = chunk_size
                    chunk_text = remaining[:split_at].strip()
                    remaining = remaining[split_at:].lstrip()
                chunks.append(
                    ParsedChunk(
                        chunk_id=f"{section_index + 1}-{chunk_index + 1}",
                        heading=section.heading,
                        content=chunk_text,
                        page_label=section.page_label,
                    )
                )
                chunk_index += 1
        return chunks
