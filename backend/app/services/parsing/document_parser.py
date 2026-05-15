"""Document parsing helpers with Docling-backed PDF normalization."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.app.core.models.domain import ParsedChunk, ParsedDocument, ParsedPicture, ParsedSection, ParsedTable


PARSER_VERSION = "docling-v1"


@dataclass(slots=True)
class DoclingTablePayload:
    """Intermediate normalized table payload."""

    table_id: str
    caption: str
    page_label: str | None
    locator: str | None
    markdown: str
    nearby_text: str


@dataclass(slots=True)
class DoclingPicturePayload:
    """Intermediate normalized picture payload."""

    picture_id: str
    caption: str
    page_label: str | None
    locator: str | None
    nearby_text: str
    bbox: list[float]


@dataclass(slots=True)
class DoclingParsePayload:
    """Intermediate PDF parse payload emitted by the Docling adapter."""

    markdown_text: str
    plain_text: str
    raw_docling: dict[str, Any]
    page_count: int | None
    tables: list[DoclingTablePayload]
    pictures: list[DoclingPicturePayload]
    title: str | None = None


class DocumentParser:
    """Parse local files into a normalized structured representation."""

    def __init__(
        self,
        max_chars: int = 120000,
        *,
        docling_enabled: bool = True,
        docling_ocr_enabled: bool = True,
        docling_artifacts_path: Path | None = None,
        docling_max_pages: int = 80,
        docling_max_file_size_mb: int = 50,
        docling_omp_threads: int = 4,
        docling_batch_size: int = 1,
        docling_device: str = "auto",
    ):
        self.max_chars = max_chars
        self.docling_enabled = docling_enabled
        self.docling_ocr_enabled = docling_ocr_enabled
        self.docling_artifacts_path = docling_artifacts_path
        self.docling_max_pages = docling_max_pages
        self.docling_max_file_size_mb = docling_max_file_size_mb
        self.docling_omp_threads = docling_omp_threads
        self.docling_batch_size = max(1, docling_batch_size)
        self.docling_device = docling_device
        self._docling_converter: Any | None = None

    def parse(self, paper_id: str, file_path: Path, *, parsed_dir: Path | None = None) -> ParsedDocument:
        """Parse a paper file into a structured document."""
        if file_path.suffix.lower() == ".pdf":
            return self._parse_pdf_docling(paper_id, file_path, parsed_dir=parsed_dir)
        return self._parse_legacy_text(paper_id, file_path)

    def build_cache_fingerprint(self, file_path: Path, *, backend: str) -> str:
        """Build a stable parser cache fingerprint for one source file."""
        stats = file_path.stat()
        payload = {
            "backend": backend,
            "parser_version": self.parser_version(backend),
            "path": str(file_path.resolve()),
            "size": stats.st_size,
            "mtime_ns": stats.st_mtime_ns,
            "max_chars": self.max_chars,
            "docling_enabled": self.docling_enabled,
            "docling_ocr_enabled": self.docling_ocr_enabled,
            "docling_max_pages": self.docling_max_pages,
            "docling_max_file_size_mb": self.docling_max_file_size_mb,
            "docling_omp_threads": self.docling_omp_threads,
            "docling_batch_size": self.docling_batch_size,
            "docling_device": self.docling_device,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    def is_cache_valid(self, parsed_doc: ParsedDocument, file_path: Path) -> bool:
        """Return whether a parsed document still matches current parser settings."""
        backend = "docling" if file_path.suffix.lower() == ".pdf" else "legacy"
        expected = self.build_cache_fingerprint(file_path, backend=backend)
        cached = parsed_doc.metadata.get("cache_fingerprint")
        if cached != expected:
            return False
        if parsed_doc.parser_backend != backend:
            return False
        if parsed_doc.parser_version != self.parser_version(backend):
            return False
        if backend == "docling":
            if not parsed_doc.markdown_path or not Path(parsed_doc.markdown_path).exists():
                return False
            if not parsed_doc.docling_json_path or not Path(parsed_doc.docling_json_path).exists():
                return False
        return True

    def parser_version(self, backend: str) -> str:
        """Return the active parser version string for one backend."""
        return PARSER_VERSION if backend == "docling" else "legacy-v1"

    def _parse_legacy_text(self, paper_id: str, file_path: Path) -> ParsedDocument:
        text = self._normalize_text(self._read_text(file_path))
        title = self._guess_title(file_path, text)
        abstract = self._extract_legacy_abstract(text)
        sections = self._split_legacy_sections(text)
        if not sections:
            sections = [
                ParsedSection(
                    section_id="section-1",
                    heading="Document Body",
                    content=text[:4000],
                    section_path="Document Body",
                    page_label=None,
                )
            ]
        chunks = self._build_semantic_chunks(sections, [], [])
        return ParsedDocument(
            paper_id=paper_id,
            source_path=str(file_path),
            title=title,
            abstract=abstract,
            sections=sections,
            chunks=chunks,
            plain_text=text,
            parser_backend="legacy",
            parser_version=self.parser_version("legacy"),
            metadata={
                "cache_fingerprint": self.build_cache_fingerprint(file_path, backend="legacy"),
                "parser_config": json.dumps(self._parser_config_summary(), ensure_ascii=False, sort_keys=True),
            },
            created_at=datetime.now(UTC),
        )

    def _parse_pdf_docling(self, paper_id: str, file_path: Path, *, parsed_dir: Path | None) -> ParsedDocument:
        self._validate_pdf_limits(file_path)
        payload = self._convert_pdf_with_docling(file_path)
        if payload.page_count is not None and payload.page_count > self.docling_max_pages:
            raise RuntimeError(
                f"PDF exceeds configured page limit ({payload.page_count} > {self.docling_max_pages}): {file_path.name}"
            )

        markdown_path: Path | None = None
        raw_json_path: Path | None = None
        if parsed_dir is not None:
            parsed_dir.mkdir(parents=True, exist_ok=True)
            raw_docling_dir = parsed_dir / "docling"
            raw_docling_dir.mkdir(parents=True, exist_ok=True)
            markdown_path = parsed_dir / f"{paper_id}.md"
            raw_json_path = raw_docling_dir / f"{paper_id}.json"
            markdown_path.write_text(payload.markdown_text, encoding="utf-8")
            raw_json_path.write_text(json.dumps(payload.raw_docling, ensure_ascii=False, indent=2), encoding="utf-8")

        title = payload.title or self._guess_title(file_path, payload.markdown_text or payload.plain_text)
        plain_text = self._normalize_text(payload.plain_text)
        sections = self._split_markdown_sections(payload.markdown_text, fallback_text=plain_text)
        abstract = self._extract_abstract(sections, plain_text)
        tables = [ParsedTable(**asdict(table)) for table in payload.tables]
        pictures = [ParsedPicture(**asdict(picture)) for picture in payload.pictures]
        self._attach_nearby_text(sections, tables, pictures)
        chunks = self._build_semantic_chunks(sections, tables, pictures)

        return ParsedDocument(
            paper_id=paper_id,
            source_path=str(file_path),
            title=title,
            abstract=abstract,
            sections=sections,
            chunks=chunks,
            plain_text=plain_text,
            parser_backend="docling",
            parser_version=self.parser_version("docling"),
            page_count=payload.page_count,
            docling_json_path=str(raw_json_path) if raw_json_path else None,
            markdown_path=str(markdown_path) if markdown_path else None,
            tables=tables,
            pictures=pictures,
            metadata={
                "cache_fingerprint": self.build_cache_fingerprint(file_path, backend="docling"),
                "parser_config": json.dumps(self._parser_config_summary(), ensure_ascii=False, sort_keys=True),
            },
            created_at=datetime.now(UTC),
        )

    def _convert_pdf_with_docling(self, file_path: Path) -> DoclingParsePayload:
        if not self.docling_enabled:
            raise RuntimeError("Docling parsing is disabled by configuration for PDF files.")

        converter = self._get_docling_converter()
        try:
            conversion_result = converter.convert(file_path, max_num_pages=self.docling_max_pages)
        except Exception as exc:
            message = str(exc)
            if any(token in message.lower() for token in ("rapidocr", "download", "modelscope", "proxyerror")):
                artifacts_hint = (
                    f" Pre-download the OCR artifacts into {self.docling_artifacts_path} or run once with network access."
                    if self.docling_artifacts_path is not None
                    else " Pre-download the required OCR artifacts or run once with network access."
                )
                raise RuntimeError(
                    "Docling failed while initializing OCR artifacts for PDF parsing."
                    f"{artifacts_hint}"
                ) from exc
            raise
        document = conversion_result.document
        markdown_text = document.export_to_markdown()
        plain_text = document.export_to_markdown(strict_text=True)
        raw_docling = document.export_to_dict()
        tables = [self._extract_docling_table(index, item) for index, item in enumerate(getattr(document, "tables", []) or [])]
        pictures = [self._extract_docling_picture(index, item) for index, item in enumerate(getattr(document, "pictures", []) or [])]

        return DoclingParsePayload(
            markdown_text=markdown_text,
            plain_text=plain_text,
            raw_docling=raw_docling,
            page_count=self._estimate_page_count(document, conversion_result, raw_docling),
            tables=tables,
            pictures=pictures,
            title=self._coerce_title(document),
        )

    def _get_docling_converter(self) -> Any:
        if self._docling_converter is not None:
            return self._docling_converter

        os.environ.setdefault("OMP_NUM_THREADS", str(self.docling_omp_threads))
        try:
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            from docling.document_converter import DocumentConverter, PdfFormatOption
        except ImportError as exc:  # pragma: no cover - exercised in real env
            raise RuntimeError(
                "Docling is required for PDF parsing but is not installed. Install the 'docling' dependency first."
            ) from exc

        pipeline_options = PdfPipelineOptions()
        option_values = {
            "do_table_structure": True,
            "do_ocr": self.docling_ocr_enabled,
            "do_picture_classification": False,
            "do_picture_description": False,
            "generate_page_images": False,
            "generate_picture_images": False,
            "enable_remote_services": False,
            "ocr_batch_size": self.docling_batch_size,
            "layout_batch_size": self.docling_batch_size,
            "table_batch_size": self.docling_batch_size,
        }
        for option_name, option_value in option_values.items():
            if hasattr(pipeline_options, option_name):
                setattr(pipeline_options, option_name, option_value)
        accelerator_options = getattr(pipeline_options, "accelerator_options", None)
        if accelerator_options is not None and hasattr(accelerator_options, "num_threads"):
            accelerator_options.num_threads = self.docling_omp_threads
        if accelerator_options is not None and hasattr(accelerator_options, "device"):
            accelerator_options.device = self.docling_device
        if self.docling_artifacts_path is not None:
            self.docling_artifacts_path.mkdir(parents=True, exist_ok=True)
            if hasattr(pipeline_options, "artifacts_path"):
                pipeline_options.artifacts_path = str(self.docling_artifacts_path)

        self._docling_converter = DocumentConverter(
            allowed_formats=[InputFormat.PDF],
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)},
        )
        return self._docling_converter

    def _parser_config_summary(self) -> dict[str, str]:
        return {
            "docling_enabled": str(self.docling_enabled),
            "docling_ocr_enabled": str(self.docling_ocr_enabled),
            "docling_max_pages": str(self.docling_max_pages),
            "docling_max_file_size_mb": str(self.docling_max_file_size_mb),
            "docling_omp_threads": str(self.docling_omp_threads),
            "docling_batch_size": str(self.docling_batch_size),
            "docling_device": self.docling_device,
            "parser_version": PARSER_VERSION,
        }

    def _validate_pdf_limits(self, file_path: Path) -> None:
        file_size_mb = file_path.stat().st_size / (1024 * 1024)
        if file_size_mb > self.docling_max_file_size_mb:
            raise RuntimeError(
                f"PDF exceeds configured file-size limit ({file_size_mb:.1f}MB > {self.docling_max_file_size_mb}MB): {file_path.name}"
            )
        page_count = self._try_read_pdf_page_count(file_path)
        if page_count is not None and page_count > self.docling_max_pages:
            raise RuntimeError(
                f"PDF exceeds configured page limit ({page_count} > {self.docling_max_pages}): {file_path.name}"
            )

    def _try_read_pdf_page_count(self, file_path: Path) -> int | None:
        try:
            import pypdfium2 as pdfium  # type: ignore

            return len(pdfium.PdfDocument(str(file_path)))
        except Exception:
            pass
        try:
            from pypdf import PdfReader  # type: ignore

            return len(PdfReader(str(file_path)).pages)
        except Exception:
            return None

    def _estimate_page_count(self, document: Any, conversion_result: Any, raw_docling: dict[str, Any]) -> int | None:
        for candidate in (getattr(document, "pages", None), getattr(conversion_result, "pages", None)):
            if candidate is not None:
                try:
                    return len(candidate)
                except TypeError:
                    pass
        pages = raw_docling.get("pages")
        if isinstance(pages, list):
            return len(pages)
        return self._max_page_from_items(raw_docling)

    def _max_page_from_items(self, raw_docling: dict[str, Any]) -> int | None:
        max_page = 0
        for key in ("texts", "tables", "pictures"):
            values = raw_docling.get(key)
            if not isinstance(values, list):
                continue
            for item in values:
                prov = item.get("prov") if isinstance(item, dict) else None
                if not isinstance(prov, list):
                    continue
                for prov_item in prov:
                    page_no = prov_item.get("page_no") if isinstance(prov_item, dict) else None
                    if isinstance(page_no, int):
                        max_page = max(max_page, page_no)
        return max_page or None

    def _guess_title(self, file_path: Path, text: str) -> str:
        for line in text.splitlines():
            stripped = line.strip("# ").strip()
            if stripped:
                return stripped[:160]
        return file_path.stem

    def _extract_legacy_abstract(self, text: str) -> str:
        match = re.search(r"(?is)\babstract\b[:\s]*(.+?)(?:\n\s*\n|\b1\b|\bintroduction\b)", text)
        if match:
            return match.group(1).strip()[:2000]
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        return paragraphs[0][:2000] if paragraphs else ""

    def _extract_abstract(self, sections: list[ParsedSection], plain_text: str) -> str:
        for section in sections:
            if "abstract" in section.heading.lower():
                return section.content[:2000]
        paragraphs = [p.strip() for p in plain_text.split("\n\n") if p.strip()]
        return paragraphs[0][:2000] if paragraphs else ""

    def _split_markdown_sections(self, markdown_text: str, *, fallback_text: str) -> list[ParsedSection]:
        matches = list(re.finditer(r"(?m)^(#{1,6})\s+(.+?)\s*$", markdown_text))
        if not matches:
            return self._fallback_sections_from_text(fallback_text)

        sections: list[ParsedSection] = []
        for index, match in enumerate(matches):
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown_text)
            heading = match.group(2).strip()
            content = markdown_text[start:end].strip()
            if not content:
                continue
            sections.append(
                ParsedSection(
                    section_id=f"section-{index + 1}",
                    heading=heading,
                    content=content[:7000],
                    section_path=heading,
                    page_label=None,
                )
            )
        return sections or self._fallback_sections_from_text(fallback_text)

    def _split_legacy_sections(self, text: str) -> list[ParsedSection]:
        heading_pattern = re.compile(
            r"(?m)^(?:\d+(?:\.\d+)*)?\s*(Introduction|Background|Related Work|Method|Methods|Approach|Experiments|Results|Discussion|Conclusion|Limitations)\b.*$"
        )
        matches = list(heading_pattern.finditer(text))
        if not matches:
            return self._fallback_sections_from_text(text)

        sections: list[ParsedSection] = []
        for index, match in enumerate(matches):
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            heading = match.group(0).strip()
            content = text[start:end].strip()
            sections.append(
                ParsedSection(
                    section_id=f"section-{index + 1}",
                    heading=heading,
                    content=content[:5000],
                    section_path=heading,
                    page_label=None,
                )
            )
        return sections

    def _fallback_sections_from_text(self, text: str) -> list[ParsedSection]:
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        return [
            ParsedSection(
                section_id=f"section-{index + 1}",
                heading=f"Section {index + 1}",
                content=paragraph[:3000],
                section_path=f"Section {index + 1}",
                page_label=None,
            )
            for index, paragraph in enumerate(paragraphs[:8])
        ]

    def _attach_nearby_text(
        self,
        sections: list[ParsedSection],
        tables: list[ParsedTable],
        pictures: list[ParsedPicture],
    ) -> None:
        narrative_context = " ".join(section.content[:500] for section in sections[:2])
        for table in tables:
            table.nearby_text = self._select_nearby_text(sections, table.caption, fallback=narrative_context)
        for picture in pictures:
            picture.nearby_text = self._select_nearby_text(sections, picture.caption, fallback=narrative_context)

    def _select_nearby_text(self, sections: list[ParsedSection], caption: str, *, fallback: str) -> str:
        caption_tokens = [token for token in re.split(r"\W+", caption.lower()) if len(token) > 3]
        for section in sections:
            lowered = section.content.lower()
            if caption_tokens and any(token in lowered for token in caption_tokens[:4]):
                return section.content[:900]
        return fallback[:900]

    def _build_semantic_chunks(
        self,
        sections: list[ParsedSection],
        tables: list[ParsedTable],
        pictures: list[ParsedPicture],
        *,
        chunk_size: int = 1600,
    ) -> list[ParsedChunk]:
        chunks: list[ParsedChunk] = []
        for section in sections:
            paragraphs = [paragraph.strip() for paragraph in section.content.split("\n\n") if paragraph.strip()]
            buffer: list[str] = []
            chunk_index = 1
            for paragraph in paragraphs:
                candidate = "\n\n".join([*buffer, paragraph]).strip()
                if buffer and len(candidate) > chunk_size:
                    chunks.append(self._make_narrative_chunk(section, chunk_index, "\n\n".join(buffer).strip()))
                    chunk_index += 1
                    buffer = [paragraph]
                else:
                    buffer.append(paragraph)
            if buffer:
                chunks.append(self._make_narrative_chunk(section, chunk_index, "\n\n".join(buffer).strip()))

        for table in tables:
            content = "\n".join(
                part
                for part in (f"Table {table.caption}".strip(), table.markdown.strip(), table.nearby_text.strip())
                if part
            )
            page_number = int(table.page_label) if table.page_label and table.page_label.isdigit() else None
            chunks.append(
                ParsedChunk(
                    chunk_id=f"chunk-{table.table_id}",
                    heading=table.caption or table.table_id,
                    content=content[:3000],
                    chunk_type="table",
                    page_label=table.page_label,
                    page_start=page_number,
                    page_end=page_number,
                    section_path="Tables",
                    table_refs=[table.table_id],
                    rank_text=self._build_rank_text(
                        heading=table.caption or table.table_id,
                        content=content,
                        section_path="Tables",
                        extras=[table.table_id, "table", table.locator or ""],
                    ),
                )
            )

        for picture in pictures:
            content = "\n".join(part for part in (f"Figure {picture.caption}".strip(), picture.nearby_text.strip()) if part)
            page_number = int(picture.page_label) if picture.page_label and picture.page_label.isdigit() else None
            chunks.append(
                ParsedChunk(
                    chunk_id=f"chunk-{picture.picture_id}",
                    heading=picture.caption or picture.picture_id,
                    content=content[:2200],
                    chunk_type="figure",
                    page_label=picture.page_label,
                    page_start=page_number,
                    page_end=page_number,
                    section_path="Figures",
                    picture_refs=[picture.picture_id],
                    rank_text=self._build_rank_text(
                        heading=picture.caption or picture.picture_id,
                        content=content,
                        section_path="Figures",
                        extras=[picture.picture_id, "figure", picture.locator or ""],
                    ),
                )
            )
        return chunks

    def _make_narrative_chunk(self, section: ParsedSection, chunk_index: int, content: str) -> ParsedChunk:
        return ParsedChunk(
            chunk_id=f"{section.section_id or section.heading}-{chunk_index}",
            heading=section.heading,
            content=content[:2200],
            chunk_type="narrative",
            page_label=section.page_label,
            page_start=section.page_start,
            page_end=section.page_end,
            section_path=section.section_path or section.heading,
            rank_text=self._build_rank_text(
                heading=section.heading,
                content=content,
                section_path=section.section_path or section.heading,
            ),
        )

    def _build_rank_text(self, *, heading: str, content: str, section_path: str, extras: list[str] | None = None) -> str:
        values = [section_path, heading, *(extras or []), content]
        return " ".join(value.strip() for value in values if value and value.strip())

    def _coerce_title(self, document: Any) -> str | None:
        for attr in ("name", "title"):
            value = getattr(document, attr, None)
            if isinstance(value, str) and value.strip():
                return value.strip()[:160]
        return None

    def _extract_docling_table(self, index: int, item: Any) -> DoclingTablePayload:
        table_id = self._coerce_identifier(item, fallback=f"table-{index + 1}")
        page_label = self._extract_page_label(item)
        caption = self._extract_caption(item)
        locator = f"p.{page_label} / {table_id}" if page_label else table_id
        markdown = self._export_table_markdown(item)
        return DoclingTablePayload(
            table_id=table_id,
            caption=caption,
            page_label=page_label,
            locator=locator,
            markdown=markdown[:6000],
            nearby_text="",
        )

    def _extract_docling_picture(self, index: int, item: Any) -> DoclingPicturePayload:
        picture_id = self._coerce_identifier(item, fallback=f"figure-{index + 1}")
        page_label = self._extract_page_label(item)
        caption = self._extract_caption(item)
        locator = f"p.{page_label} / {picture_id}" if page_label else picture_id
        return DoclingPicturePayload(
            picture_id=picture_id,
            caption=caption,
            page_label=page_label,
            locator=locator,
            nearby_text="",
            bbox=self._extract_bbox(item),
        )

    def _coerce_identifier(self, item: Any, *, fallback: str) -> str:
        for attr in ("self_ref", "label", "id"):
            value = getattr(item, attr, None)
            if isinstance(value, str) and value.strip():
                return value.strip().replace("#", "").replace("/", "-")
        return fallback

    def _extract_page_label(self, item: Any) -> str | None:
        prov_items = getattr(item, "prov", None)
        if not prov_items:
            return None
        page_no = getattr(prov_items[0], "page_no", None)
        return str(page_no) if isinstance(page_no, int) else None

    def _extract_bbox(self, item: Any) -> list[float]:
        prov_items = getattr(item, "prov", None)
        if not prov_items:
            return []
        bbox = getattr(prov_items[0], "bbox", None)
        if bbox is None:
            return []
        if isinstance(bbox, (list, tuple)):
            return [float(value) for value in bbox[:4]]
        values: list[float] = []
        for attr in ("l", "t", "r", "b"):
            value = getattr(bbox, attr, None)
            if value is None:
                return []
            values.append(float(value))
        return values

    def _extract_caption(self, item: Any) -> str:
        captions = getattr(item, "captions", None)
        if captions is None:
            return ""
        parts: list[str] = []
        for caption in captions:
            text = getattr(caption, "text", None)
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
            elif isinstance(caption, str) and caption.strip():
                parts.append(caption.strip())
        return " ".join(parts)[:400]

    def _export_table_markdown(self, item: Any) -> str:
        exporter = getattr(item, "export_to_markdown", None)
        if callable(exporter):
            try:
                return str(exporter())
            except Exception:
                pass
        exporter = getattr(item, "export_to_dataframe", None)
        if callable(exporter):
            try:
                dataframe = exporter()
                to_markdown = getattr(dataframe, "to_markdown", None)
                if callable(to_markdown):
                    return str(to_markdown(index=False))
                return str(dataframe)
            except Exception:
                pass
        return ""

    def _normalize_text(self, text: str) -> str:
        text = text.replace("\r\n", "\n")
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()[: self.max_chars]

    def _read_text(self, file_path: Path) -> str:
        try:
            return file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return file_path.read_text(encoding="utf-8", errors="ignore")
