from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.services.parsing.document_parser import (
    DoclingParsePayload,
    DoclingPicturePayload,
    DoclingTablePayload,
    DocumentParser,
)


def test_document_parser_normalizes_docling_pdf(monkeypatch, isolated_session_root: Path) -> None:
    pdf_path = isolated_session_root / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n% fake pdf for parser tests\n")
    parsed_dir = isolated_session_root / "parsed"
    parser = DocumentParser(
        docling_enabled=True,
        docling_artifacts_path=isolated_session_root / ".cache" / "docling",
    )

    def fake_convert(_file_path: Path) -> DoclingParsePayload:
        return DoclingParsePayload(
            markdown_text="# Sample Paper\n\n## Abstract\nA concise abstract.\n\n## Method\nWe propose a method.\n\n## Results\nSee Table 1 and Figure 1.",
            plain_text="Sample Paper\n\nA concise abstract.\n\nWe propose a method.\n\nSee Table 1 and Figure 1.",
            raw_docling={"pages": [{}, {}], "texts": [], "tables": [], "pictures": []},
            page_count=2,
            tables=[
                DoclingTablePayload(
                    table_id="table-1",
                    caption="Main results",
                    page_label="2",
                    locator="p.2 / table-1",
                    markdown="| metric | value |\n| --- | --- |\n| acc | 91 |",
                    nearby_text="",
                )
            ],
            pictures=[
                DoclingPicturePayload(
                    picture_id="figure-1",
                    caption="Pipeline overview",
                    page_label="2",
                    locator="p.2 / figure-1",
                    nearby_text="",
                    bbox=[0.0, 0.0, 100.0, 100.0],
                )
            ],
            title="Sample Paper",
        )

    monkeypatch.setattr(parser, "_convert_pdf_with_docling", fake_convert)

    parsed = parser.parse("paper-1", pdf_path, parsed_dir=parsed_dir)

    assert parsed.parser_backend == "docling"
    assert parsed.page_count == 2
    assert parsed.abstract.startswith("A concise abstract")
    assert parsed.tables and parsed.tables[0].table_id == "table-1"
    assert parsed.pictures and parsed.pictures[0].picture_id == "figure-1"
    assert any(chunk.chunk_type == "table" for chunk in parsed.chunks)
    assert any(chunk.chunk_type == "figure" for chunk in parsed.chunks)
    assert parsed.markdown_path and Path(parsed.markdown_path).exists()
    assert parsed.docling_json_path and Path(parsed.docling_json_path).exists()
    assert parser.is_cache_valid(parsed, pdf_path)

    pdf_path.write_bytes(b"%PDF-1.4\n% updated pdf for parser tests\n")
    assert not parser.is_cache_valid(parsed, pdf_path)


def test_document_parser_keeps_text_fallback_for_non_pdf(isolated_session_root: Path) -> None:
    text_path = isolated_session_root / "sample.txt"
    text_path.write_text(
        "A Great Paper\n\nAbstract This paper studies a simple method.\n\nMethod\nThe method has two stages.\n",
        encoding="utf-8",
    )
    parser = DocumentParser(docling_enabled=True)

    parsed = parser.parse("paper-1", text_path)

    assert parsed.parser_backend == "legacy"
    assert parsed.sections
    assert parsed.chunks
    assert parsed.metadata["cache_fingerprint"]


def test_document_parser_surfaces_docling_artifact_hint(monkeypatch, isolated_session_root: Path) -> None:
    pdf_path = isolated_session_root / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n% fake pdf for parser tests\n")
    parser = DocumentParser(
        docling_enabled=True,
        docling_artifacts_path=isolated_session_root / ".cache" / "docling",
    )

    class BrokenConverter:
        def convert(self, _file_path: Path) -> None:
            raise RuntimeError("RapidOCR download failed from modelscope")

    monkeypatch.setattr(parser, "_get_docling_converter", lambda: BrokenConverter())

    with pytest.raises(RuntimeError, match="Pre-download the OCR artifacts"):
        parser.parse("paper-1", pdf_path, parsed_dir=isolated_session_root / "parsed")
