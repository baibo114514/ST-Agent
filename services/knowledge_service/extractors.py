"""
文档文本提取。
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException, status

try:
    import fitz

    PDF_AVAILABLE = True
except ImportError:
    fitz = None
    PDF_AVAILABLE = False


TEXT_MIME_PREFIXES = ("text/",)
TEXT_EXTENSIONS = (".txt", ".md", ".markdown", ".csv", ".json", ".html", ".htm", ".log")
TEXT_DECODINGS = ("utf-8-sig", "utf-8", "gb18030", "gbk", "utf-16")
MARKDOWN_FIELD_RE = re.compile(
    r"^(?P<indent>[ \t]*)-\s+(?:\*\*(?P<bold_key>.+?)\*\*|(?P<plain_key>[^:：]+?))\s*[:：]\s*(?P<value>.*?)\s*$"
)
YAML_FIELD_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<key>[^:：\n]+?)\s*[:：]\s*(?P<value>.*?)\s*$"
)
HEADING_RE = re.compile(r"^\s*#\s+(?P<title>.+?)\s*$")


def decode_text_bytes(body: bytes) -> str:
    for encoding in TEXT_DECODINGS:
        try:
            return body.decode(encoding)
        except UnicodeDecodeError:
            continue
    return body.decode("utf-8", errors="replace")


def _parse_text_value(value: str) -> str:
    """Keep extracted metadata as text; type conversion belongs to mappings."""
    return value.strip()


def _indent_width(value: str) -> int:
    return len(value.expandtabs(4)) - len(value.lstrip(" \t").expandtabs(4))


def _flush_field(metadata: dict[str, str], key: str | None, values: list[str]) -> None:
    if key is None:
        return
    metadata[key] = "\n".join(values).strip()


def _parse_markdown_fields(
    lines: list[str],
    start: int,
    max_lines: int,
) -> tuple[dict[str, str], int, str | None]:
    metadata: dict[str, str] = {}
    field_key: str | None = None
    field_values: list[str] = []
    field_indent: int | None = None
    metadata_started = False
    cursor = start
    limit = min(len(lines), start + max_lines)

    while cursor < limit:
        line = lines[cursor]
        if line.strip() == "---" and metadata_started:
            _flush_field(metadata, field_key, field_values)
            return metadata, cursor + 1, "markdown_metadata_block"

        match = MARKDOWN_FIELD_RE.match(line)
        line_indent = _indent_width(line)
        same_level_field = match and (field_indent is None or line_indent == field_indent)
        if same_level_field:
            _flush_field(metadata, field_key, field_values)
            field_key = (match.group("bold_key") or match.group("plain_key") or "").strip()
            field_values = [_parse_text_value(match.group("value"))]
            field_indent = line_indent if field_indent is None else field_indent
            metadata_started = True
            cursor += 1
            continue

        if not metadata_started:
            if not line.strip():
                cursor += 1
                continue
            break

        # Any deeper-indented line, including nested lists, belongs to the
        # current field. Blank lines are retained as part of its text value.
        if not line.strip() or line_indent > (field_indent or 0):
            field_values.append(_parse_text_value(line))
            cursor += 1
            continue
        break

    _flush_field(metadata, field_key, field_values)
    return metadata, 0, None


def _parse_yaml_fields(
    lines: list[str],
    start: int,
    max_lines: int,
) -> tuple[dict[str, str], int, str | None]:
    metadata: dict[str, str] = {}
    field_key: str | None = None
    field_values: list[str] = []
    field_indent: int | None = None
    cursor = start
    limit = min(len(lines), start + max_lines)

    while cursor < limit:
        line = lines[cursor]
        if line.strip() == "---":
            _flush_field(metadata, field_key, field_values)
            return metadata, cursor + 1, "yaml_front_matter"

        match = YAML_FIELD_RE.match(line)
        line_indent = _indent_width(line)
        same_level_field = match and (field_indent is None or line_indent == field_indent)
        if same_level_field:
            _flush_field(metadata, field_key, field_values)
            field_key = match.group("key").strip()
            field_values = [_parse_text_value(match.group("value"))]
            field_indent = line_indent if field_indent is None else field_indent
            cursor += 1
            continue

        if field_key is not None and (not line.strip() or line_indent > (field_indent or 0)):
            field_values.append(_parse_text_value(line))
            cursor += 1
            continue
        break

    _flush_field(metadata, field_key, field_values)
    return metadata, 0, None


def extract_markdown_front_matter(
    text: str,
    extraction_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract YAML front matter or the policy-style heading metadata block."""
    config = extraction_config or {"enabled": True, "format": "markdown_fields", "stripExtractedBlock": True}
    if not config.get("enabled", True) or config.get("format") == "none":
        return {"metadata": {}, "contentText": text, "title": None, "sourceType": None}
    extraction_format = config.get("format", "markdown_fields")
    strip_block = bool(config.get("stripExtractedBlock", True))
    max_lines = max(10, min(int(config.get("maxLines", 100)), 500))
    lines = text.splitlines()
    if not lines:
        return {"metadata": {}, "contentText": text, "title": None, "sourceType": None}

    metadata: dict[str, str] = {}
    title: str | None = None
    end_index = 0
    source_type: str | None = None
    cursor = 0
    if lines[0].strip() == "---":
        source_type = "yaml_front_matter"
        metadata, end_index, source_type = _parse_yaml_fields(lines, 1, max_lines)
    else:
        if extraction_format != "markdown_fields":
            return {"metadata": {}, "contentText": text, "title": None, "sourceType": None}
        heading_match = HEADING_RE.match(lines[0])
        if not heading_match:
            return {"metadata": {}, "contentText": text, "title": None, "sourceType": None}
        title = heading_match.group("title").strip()
        metadata, end_index, source_type = _parse_markdown_fields(lines, 1, max_lines)

    if not end_index:
        return {"metadata": metadata, "contentText": text, "title": title, "sourceType": source_type}
    content = "\n".join(lines[end_index:]).strip() if strip_block else text
    if title and "title" not in metadata:
        metadata["title"] = title
    return {"metadata": metadata, "contentText": content, "title": title, "sourceType": source_type}


def extract_text_from_bytes(
    file_name: str,
    mime_type: str | None,
    body: bytes,
    metadata_extraction_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    name = file_name.lower()
    content_type = (mime_type or "").lower()

    if name.endswith(".pdf") or content_type == "application/pdf":
        if not PDF_AVAILABLE:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"code": "PDF_UNAVAILABLE", "message": "PyMuPDF is not installed"},
            )
        document = fitz.open(stream=body, filetype="pdf")
        pages = [page.get_text() for page in document]
        text = "\n".join(pages).strip()
        return {"title": file_name, "contentText": text, "pages": len(pages)}

    if content_type.startswith(TEXT_MIME_PREFIXES) or name.endswith(TEXT_EXTENSIONS):
        text = decode_text_bytes(body).strip()
        front_matter = (
            extract_markdown_front_matter(text, metadata_extraction_config)
            if name.endswith((".md", ".markdown"))
            else {}
        )
        if front_matter:
            return {
                "title": front_matter.get("title") or (front_matter.get("metadata") or {}).get("title") or file_name,
                "contentText": str(front_matter.get("contentText") or "").strip(),
                "metadata": front_matter.get("metadata") or {},
                "metadataSource": front_matter.get("sourceType"),
                "pages": 0,
            }
        return {"title": file_name, "contentText": text, "pages": 0, "metadata": {}}

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": "UNSUPPORTED_FILE", "message": "only PDF and text-like documents are supported"},
    )
