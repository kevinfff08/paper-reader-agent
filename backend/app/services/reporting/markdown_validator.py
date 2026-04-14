"""Lightweight Markdown validation and safe normalization for archive output."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


_MERMAID_PREFIXES = (
    "graph ",
    "flowchart ",
    "sequencediagram",
    "classdiagram",
    "statediagram",
    "statediagram-v2",
    "erdiagram",
    "journey",
    "gantt",
    "pie ",
    "mindmap",
    "timeline",
    "quadrantchart",
    "requirementdiagram",
    "gitgraph",
    "c4context",
    "c4container",
    "c4component",
    "c4dynamic",
    "c4deployment",
)

_EXTERNAL_PREFIXES = ("http://", "https://", "data:", "mailto:")


@dataclass(slots=True)
class MarkdownWarning:
    """One validation warning."""

    warning_type: str
    line: int | None
    message: str

    def as_dict(self) -> dict[str, object]:
        return {"warning_type": self.warning_type, "line": self.line, "message": self.message}


@dataclass(slots=True)
class ValidationResult:
    """Result of Markdown validation."""

    markdown: str
    warnings: list[MarkdownWarning]

    def warnings_as_json(self) -> str:
        return json.dumps([warning.as_dict() for warning in self.warnings], ensure_ascii=False, indent=2) + "\n"

    def warnings_as_markdown(self) -> str:
        if not self.warnings:
            return "# Archive Warnings\n\nNo warnings were recorded.\n"
        lines = ["# Archive Warnings", ""]
        for warning in self.warnings:
            location = f"line {warning.line}" if warning.line is not None else "unknown line"
            lines.append(f"- `{warning.warning_type}` at {location}: {warning.message}")
        lines.append("")
        return "\n".join(lines)


class MarkdownValidator:
    """Apply low-risk cleanup and non-blocking warnings."""

    def validate(self, markdown: str, *, base_dir: Path | None = None) -> ValidationResult:
        warnings: list[MarkdownWarning] = []
        normalized = markdown.replace("\r\n", "\n").replace("\r", "\n")
        lines = normalized.split("\n")
        cleaned_lines: list[str] = []
        in_code_block = False
        current_fence = ""
        current_language = ""
        mermaid_buffer: list[str] = []
        mermaid_opening_index: int | None = None
        mermaid_start_line: int | None = None
        previous_heading_level = 0
        script_block = False

        for index, line in enumerate(lines, start=1):
            stripped = line.strip()

            if script_block:
                if re.search(r"</(script|style|iframe)>", stripped, flags=re.IGNORECASE):
                    script_block = False
                continue

            if not in_code_block and re.match(r"<(script|style|iframe)\b", stripped, flags=re.IGNORECASE):
                warnings.append(MarkdownWarning("raw_html_stripped", index, "Removed raw HTML script/style/iframe block."))
                if not re.search(r"</(script|style|iframe)>", stripped, flags=re.IGNORECASE):
                    script_block = True
                continue

            fence_match = re.match(r"^(```+|~~~+)\s*([A-Za-z0-9_-]*)\s*$", line)
            if fence_match:
                marker = fence_match.group(1)
                language = fence_match.group(2).strip().lower()
                if not in_code_block:
                    in_code_block = True
                    current_fence = marker
                    current_language = language
                    if language == "mermaid":
                        mermaid_buffer = []
                        mermaid_start_line = index
                        mermaid_opening_index = len(cleaned_lines)
                    cleaned_lines.append(line)
                    continue
                if marker == current_fence:
                    if current_language == "mermaid" and not self._is_valid_mermaid(mermaid_buffer):
                        warnings.append(
                            MarkdownWarning(
                                "invalid_mermaid",
                                mermaid_start_line,
                                "Invalid mermaid block was downgraded to a plain fenced code block.",
                            )
                        )
                        if mermaid_opening_index is not None:
                            cleaned_lines[mermaid_opening_index] = current_fence
                    in_code_block = False
                    current_fence = ""
                    current_language = ""
                    mermaid_buffer = []
                    mermaid_opening_index = None
                    mermaid_start_line = None
                cleaned_lines.append(line)
                continue

            if in_code_block:
                if current_language == "mermaid":
                    mermaid_buffer.append(line)
                cleaned_lines.append(line)
                continue

            if (
                stripped.startswith("<")
                and stripped.endswith(">")
                and not stripped.startswith("<!--")
                and not re.match(r"<(?:https?://|mailto:)", stripped, flags=re.IGNORECASE)
            ):
                warnings.append(MarkdownWarning("raw_html_warning", index, "Raw HTML detected in archive Markdown."))

            heading_match = re.match(r"^(#{1,6})\s+.+$", stripped)
            if heading_match:
                level = len(heading_match.group(1))
                if previous_heading_level and level > previous_heading_level + 1:
                    warnings.append(
                        MarkdownWarning("heading_jump", index, f"Heading level jumps from H{previous_heading_level} to H{level}.")
                    )
                previous_heading_level = level

            for match in re.finditer(r"!\[[^\]]*]\(([^)]*)\)", line):
                target = match.group(1).strip()
                if not target:
                    warnings.append(MarkdownWarning("broken_image", index, "Image target is empty."))
                    continue
                if target.startswith(_EXTERNAL_PREFIXES):
                    continue
                if base_dir is not None and not self._image_exists(target, base_dir):
                    warnings.append(MarkdownWarning("missing_image", index, f"Image target not found: {target}"))

            cleaned_lines.append(line)

        if in_code_block:
            warnings.append(MarkdownWarning("unclosed_fence", len(lines), "Automatically closed an unterminated fenced block."))
            cleaned_lines.append(current_fence or "```")

        normalized = "\n".join(cleaned_lines)
        normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip() + "\n"
        warnings.extend(self._check_pipe_tables(normalized))
        warnings.extend(self._check_math_balance(normalized))
        return ValidationResult(markdown=normalized, warnings=warnings)

    def _is_valid_mermaid(self, lines: list[str]) -> bool:
        first_nonempty = next((line.strip().lower() for line in lines if line.strip()), "")
        return any(first_nonempty.startswith(prefix) for prefix in _MERMAID_PREFIXES)

    def _image_exists(self, target: str, base_dir: Path) -> bool:
        candidate = Path(target)
        if candidate.is_absolute():
            return candidate.exists()
        archive_relative = (base_dir / target).resolve()
        session_relative = (base_dir.parent / target).resolve()
        return archive_relative.exists() or session_relative.exists()

    def _check_pipe_tables(self, markdown: str) -> list[MarkdownWarning]:
        warnings: list[MarkdownWarning] = []
        lines = markdown.splitlines()
        index = 0
        while index < len(lines) - 1:
            line = lines[index].strip()
            next_line = lines[index + 1].strip()
            if "|" in line and re.match(r"^\|?[\s:-]+\|[\s|:-]*$", next_line):
                expected = line.count("|")
                pointer = index + 2
                while pointer < len(lines) and "|" in lines[pointer]:
                    if lines[pointer].count("|") != expected:
                        warnings.append(
                            MarkdownWarning(
                                "table_shape",
                                pointer + 1,
                                "Pipe table row has a different column count than the header row.",
                            )
                        )
                        break
                    pointer += 1
                index = pointer
                continue
            index += 1
        return warnings

    def _check_math_balance(self, markdown: str) -> list[MarkdownWarning]:
        warnings: list[MarkdownWarning] = []
        lines = markdown.splitlines()
        block_math_count = 0
        inline_warning_count = 0
        in_code_block = False
        for index, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith("```") or stripped.startswith("~~~"):
                in_code_block = not in_code_block
                continue
            if in_code_block:
                continue
            block_math_count += len(re.findall(r"(?<!\\)\$\$", line))
            without_blocks = re.sub(r"(?<!\\)\$\$", "", line)
            inline_count = len(re.findall(r"(?<!\\)\$", without_blocks))
            if inline_count % 2 != 0 and inline_warning_count < 4:
                warnings.append(MarkdownWarning("math_balance", index, "Unbalanced inline math delimiter detected."))
                inline_warning_count += 1
        if block_math_count % 2 != 0:
            warnings.append(MarkdownWarning("math_block_balance", None, "Unbalanced block math delimiter detected."))
        return warnings
