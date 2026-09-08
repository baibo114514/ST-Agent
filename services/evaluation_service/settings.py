"""Settings for evaluation runners."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from services.evaluation_service.profiles import normalize_namespace_label


def _load_env_files() -> None:
    root = Path(__file__).resolve().parents[2]
    app_env = os.getenv("APP_ENV", "development")
    for file_name in (f".env.{app_env}.local", f".env.{app_env}", ".env.local", ".env"):
        env_path = root / file_name
        if env_path.is_file():
            load_dotenv(env_path, override=False)


def _parse_list(value: str | None, default: list[str] | None = None) -> list[str]:
    if not value:
        return list(default or [])
    raw = value.strip().strip("\"'")
    if not raw:
        return list(default or [])
    parts = [part.strip() for part in raw.split(",")]
    return [part for part in parts if part]


def _parse_int(value: str | None, default: int) -> int:
    if value is None or not value.strip():
        return default
    return int(value)


def _parse_float(value: str | None, default: float) -> float:
    if value is None or not value.strip():
        return default
    return float(value)


_load_env_files()

SERVICE_ROOT = Path(__file__).resolve().parent
DEFAULT_CASES_PATH = SERVICE_ROOT / "data" / "questions" / "retrieval_smoke.jsonl"
DEFAULT_OUTPUT_DIR = SERVICE_ROOT / "results" / "retrieval"


@dataclass(slots=True)
class RetrievalEvalConfig:
    """检索评估配置。所有字段均可被 EVAL_* 环境变量覆盖，详见 README「环境变量」节。"""

    # knowledge-service 连接与鉴权
    knowledge_service_base_url: str = field(
        default_factory=lambda: os.getenv(
            "EVAL_KNOWLEDGE_SERVICE_BASE_URL",
            os.getenv("KNOWLEDGE_SERVICE_BASE_URL", "http://127.0.0.1:8010"),
        )
    )
    knowledge_service_token: str = field(
        default_factory=lambda: os.getenv(
            "EVAL_KNOWLEDGE_SERVICE_TOKEN",
            os.getenv("KNOWLEDGE_SERVICE_TOKEN", ""),
        )
    )
    search_path: str = field(default_factory=lambda: os.getenv("EVAL_KNOWLEDGE_SEARCH_PATH", "/internal/v1/kb/search"))
    documents_path_template: str = field(
        default_factory=lambda: os.getenv(
            "EVAL_KNOWLEDGE_DOCUMENTS_PATH_TEMPLATE",
            "/internal/v1/kb/bases/{kb_id}/documents",
        )
    )
    # 用例与输出
    cases_path: Path = field(
        default_factory=lambda: Path(os.getenv("EVAL_CASES_PATH", str(DEFAULT_CASES_PATH)))
    )
    output_dir: Path = field(
        default_factory=lambda: Path(os.getenv("EVAL_OUTPUT_DIR", str(DEFAULT_OUTPUT_DIR)))
    )
    # 检索默认参数（用例未指定时生效）
    default_kb_ids: list[str] = field(
        default_factory=lambda: _parse_list(
            os.getenv("EVAL_KB_IDS") or os.getenv("EVAL_KB_ID"),
            default=[],
        )
    )
    top_k: int = field(default_factory=lambda: _parse_int(os.getenv("EVAL_TOP_K"), 5))
    score_threshold: float = field(default_factory=lambda: _parse_float(os.getenv("EVAL_SCORE_THRESHOLD"), 0.0))
    strategy: str | None = field(default_factory=lambda: os.getenv("EVAL_STRATEGY") or None)
    namespace: str | None = field(default_factory=lambda: normalize_namespace_label(os.getenv("EVAL_NAMESPACE")))
    request_interval_seconds: float = field(
        default_factory=lambda: _parse_float(os.getenv("EVAL_REQUEST_INTERVAL_SECONDS"), 1.1)
    )
    timeout_seconds: float = field(default_factory=lambda: _parse_float(os.getenv("EVAL_TIMEOUT_SECONDS"), 30.0))
    document_page_size: int = field(default_factory=lambda: _parse_int(os.getenv("EVAL_DOCUMENT_PAGE_SIZE"), 200))
    # 业务级指标判定阈值
    local_priority_threshold: float = field(
        default_factory=lambda: _parse_float(os.getenv("EVAL_LOCAL_PRIORITY_THRESHOLD"), 0.6)
    )
    freshness_threshold: float = field(
        default_factory=lambda: _parse_float(os.getenv("EVAL_FRESHNESS_THRESHOLD"), 0.8)
    )
    chunk_anchor_threshold: float = field(
        default_factory=lambda: _parse_float(os.getenv("EVAL_CHUNK_ANCHOR_THRESHOLD"), 1.0)
    )
    industry_relevance_threshold: float = field(
        default_factory=lambda: _parse_float(os.getenv("EVAL_INDUSTRY_RELEVANCE_THRESHOLD"), 0.7)
    )
    support_mode_relevance_threshold: float = field(
        default_factory=lambda: _parse_float(os.getenv("EVAL_SUPPORT_MODE_RELEVANCE_THRESHOLD"), 0.7)
    )
    policy_type_relevance_threshold: float = field(
        default_factory=lambda: _parse_float(os.getenv("EVAL_POLICY_TYPE_RELEVANCE_THRESHOLD"), 0.7)
    )
    negative_max_score: float = field(
        default_factory=lambda: _parse_float(os.getenv("EVAL_NEGATIVE_MAX_SCORE"), 0.35)
    )
    # 运行时控制
    generate_report: bool = True
    limit: int | None = field(default=None)
    case_ids: list[str] = field(default_factory=list)
