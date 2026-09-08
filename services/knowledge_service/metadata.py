"""Generic, configuration-driven document metadata handling."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Dict

import jieba
from fastapi import HTTPException, status

from app.core.logging import logger

SYSTEM_METADATA_KEYS = {"blobSha256", "source", "metadataSource", "relativePath", "fileName"}
METADATA_EXTRACTION_FORMATS = {"markdown_fields", "yaml_front_matter", "none"}
DEFAULT_MAPPING_CONFIG = {
    "schema": {"name": "generic", "version": "1"},
    "mappings": {},
    "defaults": {},
    "keepUnmappedInDomain": True,
}


def default_metadata_extraction_config() -> Dict[str, Any]:
    return {
        "enabled": True,
        "format": "markdown_fields",
        "stripExtractedBlock": True,
        "maxLines": 100,
        **deepcopy(DEFAULT_MAPPING_CONFIG),
    }


def normalize_metadata_extraction_config(value: Dict[str, Any] | None) -> Dict[str, Any]:
    if value is None:
        return default_metadata_extraction_config()
    if not isinstance(value, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_METADATA_EXTRACTION", "message": "metadataExtractionJson must be object"},
        )
    result = {**default_metadata_extraction_config(), **value}
    schema = result.get("schema")
    if not isinstance(schema, dict) or not str(schema.get("name") or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_METADATA_EXTRACTION", "message": "schema.name is required"},
        )
    result["schema"] = {
        "name": str(schema["name"]).strip()[:64],
        "version": str(schema.get("version") or "1").strip()[:32],
    }
    mappings = result.get("mappings")
    if not isinstance(mappings, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_METADATA_EXTRACTION", "message": "mappings must be object"},
        )
    for source_key, target in mappings.items():
        if not str(source_key).strip() or not _mapping_target(target):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "INVALID_METADATA_EXTRACTION", "message": "mapping targets must be valid paths"},
            )
    defaults = result.get("defaults")
    if not isinstance(defaults, dict) or any(not _valid_target_path(path) for path in defaults):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_METADATA_EXTRACTION", "message": "defaults must use valid paths"},
        )
    if result.get("format") not in METADATA_EXTRACTION_FORMATS:
        allowed = ", ".join(sorted(METADATA_EXTRACTION_FORMATS))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_METADATA_EXTRACTION", "message": f"format must be one of: {allowed}"},
        )
    if not isinstance(result.get("enabled"), bool) or not isinstance(result.get("stripExtractedBlock"), bool):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_METADATA_EXTRACTION", "message": "enabled and stripExtractedBlock must be boolean"},
        )
    try:
        result["maxLines"] = max(10, min(int(result.get("maxLines", 100)), 500))
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_METADATA_EXTRACTION", "message": "maxLines must be an integer"},
        ) from exc
    result["keepUnmappedInDomain"] = bool(result.get("keepUnmappedInDomain", True))
    return result


def parse_metadata(value: str | dict[str, Any] | None) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return deepcopy(value)
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        logger.exception("knowledge_metadata_json_invalid", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_METADATA", "message": "metadata must be JSON object"},
        ) from exc
    if not isinstance(parsed, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_METADATA", "message": "metadata must be JSON object"},
        )
    return parsed


def _mapping_target(value: Any) -> str | None:
    target = value if isinstance(value, str) else value.get("path") if isinstance(value, dict) else None
    return target if _valid_target_path(target) else None


def _valid_target_path(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parts = value.split(".")
    return len(parts) >= 2 and parts[0] in {"common", "domain"} and all(part.strip() for part in parts)


def _set_path(target: Dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    current = target
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = value


def _get_path(value: Dict[str, Any], path: str) -> Any:
    current: Any = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _mapping_value(mapping: Any) -> tuple[str | None, str | None]:
    if isinstance(mapping, str):
        return mapping, None
    if isinstance(mapping, dict):
        return mapping.get("path"), mapping.get("type")
    return None, None


def _coerce(value: Any, value_type: str | None) -> Any:
    if value_type == "string":
        return str(value) if value is not None else None
    if value_type == "list":
        if isinstance(value, list):
            return value
        if value in (None, ""):
            return []
        return [item.strip() for item in str(value).replace("；", ";").replace("，", ",").replace(";", ",").split(",") if item.strip()]
    if value_type == "boolean":
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().lower()
        if normalized in {"是", "true", "1", "yes"}:
            return True
        if normalized in {"否", "false", "0", "no"}:
            return False
    return value


def normalize_metadata(
    value: str | dict[str, Any] | None,
    *,
    extracted_metadata: Dict[str, Any] | None = None,
    file_name: str | None = None,
    ingest_fields: Dict[str, Any] | None = None,
    extraction_config: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    explicit = parse_metadata(value)
    extracted = parse_metadata(extracted_metadata)
    merged = {**extracted, **explicit}
    system_fields = {key: merged[key] for key in SYSTEM_METADATA_KEYS if key in merged}
    document_fields = {key: item for key, item in merged.items() if key not in SYSTEM_METADATA_KEYS}
    config = normalize_metadata_extraction_config(extraction_config)

    if _is_canonical(explicit):
        normalized = explicit
    else:
        common: Dict[str, Any] = {}
        domain: Dict[str, Any] = {}
        for source_key, raw_value in document_fields.items():
            target, value_type = _mapping_value(config["mappings"].get(source_key))
            if target:
                converted = _coerce(raw_value, value_type)
                if converted is not None:
                    _set_path({"common": common, "domain": domain}, target, converted)
            elif config["keepUnmappedInDomain"]:
                domain[source_key] = raw_value
        structure = {"common": common, "domain": domain}
        for path, default_value in config["defaults"].items():
            if _get_path(structure, path) is None:
                _set_path(structure, path, deepcopy(default_value))
        normalized = {
            "_schema": deepcopy(config["schema"]),
            "common": common,
            "domain": domain,
            "_raw": deepcopy(document_fields),
            "_source": {
                "type": "explicit_and_extracted" if explicit and extracted else ("explicit" if explicit else "extracted"),
                "extracted": bool(extracted),
            },
        }

    ingest = normalized.setdefault("_ingest", {})
    if isinstance(ingest, dict):
        ingest.update(system_fields)
        ingest.update(ingest_fields or {})
        ingest.setdefault("fileName", file_name)
    return normalized


def _is_canonical(value: Dict[str, Any]) -> bool:
    return all(isinstance(value.get(key), dict) for key in ("_schema", "common", "domain", "_raw"))


def tokenize_for_search(text: str) -> str:
    """用 jieba 分词后拼成空格分隔字符串，供 PG to_tsvector('simple', ...) 建全文索引。

    simple 配置按空格/标点切词，对中文无分词能力，故用 jieba 在 Python 侧预先
    分词。入库时写入 search_text 列，检索时对 query 同样分词后转 tsquery。
    """
    if not text:
        return ""
    words = [word.strip() for word in jieba.cut(text) if word.strip()]
    return " ".join(words)
