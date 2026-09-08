"""Schemas for retrieval evaluation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        items = value
    elif isinstance(value, tuple) or isinstance(value, set):
        items = list(value)
    else:
        items = [value]
    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


class RetrievalCase(BaseModel):
    """Raw case used by the retrieval runner."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    case_id: str = Field(alias="id")
    intent: Optional[str] = None
    query: str
    golden: Dict[str, Any] = Field(default_factory=dict)
    golden_count: Optional[int] = None
    notes: Optional[str] = None
    kb_ids: List[str] = Field(default_factory=list, alias="kbIds")
    top_k: Optional[int] = Field(default=None, alias="topK")
    score_threshold: Optional[float] = Field(default=None, alias="scoreThreshold")
    golden_document_ids: List[str] = Field(default_factory=list, alias="goldenDocumentIds")
    golden_titles: List[str] = Field(default_factory=list, alias="goldenTitles")
    golden_source_refs: List[str] = Field(default_factory=list, alias="goldenSourceRefs")
    answerable: bool = True
    priority: int = Field(default=2, ge=1, le=3, description="业务优先级：1 最高，3 较低")
    tags: List[str] = Field(default_factory=list)
    scenario: Dict[str, Any] = Field(default_factory=dict)
    request: Dict[str, Any] = Field(default_factory=dict)
    chunk_anchors: List[str] = Field(default_factory=list, alias="chunkAnchors")
    relevance_grades: Dict[str, float] = Field(default_factory=dict, alias="relevanceGrades")
    expected_behavior: Optional[str] = Field(default=None, alias="expectedBehavior")

    @field_validator(
        "kb_ids",
        "golden_document_ids",
        "golden_titles",
        "golden_source_refs",
        "tags",
        "chunk_anchors",
        mode="before",
    )
    @classmethod
    def normalize_list_fields(cls, value: Any) -> list[str]:
        return _normalize_list(value)


class KnowledgeDocumentRecord(BaseModel):
    """Document catalog entry fetched from knowledge-service."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    document_id: str = Field(alias="id")
    kb_id: str = Field(alias="kbId")
    title: str
    ingest_status: str = Field(default="", alias="ingestStatus")
    source_ref: Optional[str] = Field(default=None, alias="sourceRef")
    file_name: Optional[str] = Field(default=None, alias="fileName")
    metadata_json: Dict[str, Any] = Field(default_factory=dict, alias="metadataJson")


class KnowledgeSearchItem(BaseModel):
    """Single search result returned by knowledge-service."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    kb_id: str = Field(alias="kbId")
    kb_name: Optional[str] = Field(default=None, alias="kbName")
    document_id: str = Field(alias="documentId")
    chunk_id: str = Field(alias="chunkId")
    title: str
    score: float = 0.0
    distance: Optional[float] = None
    content_excerpt: str = Field(default="", alias="contentExcerpt")
    source_ref: Optional[str] = Field(default=None, alias="sourceRef")


class RetrievalRankItem(BaseModel):
    rank: int
    document_id: str
    title: str
    score: float = 0.0
    region: Optional[str] = None
    published_year: Optional[int] = None
    matched: bool = False


class RetrievalCaseResult(BaseModel):
    """Evaluation result for one case."""

    case_id: str
    intent: Optional[str] = None
    query: str
    answerable: bool
    priority: int = 2
    golden_count_expected: Optional[int] = None
    golden_count_actual: int = 0
    retrieved_count: int = 0
    matched_count: int = 0
    precision_at_k: float = 0.0
    recall_at_k: float = 0.0
    mrr: float = 0.0
    ndcg_at_k: float = 0.0
    chunk_anchor_hit_rate: float = 0.0
    local_priority_score: float = 0.0
    freshness_score: float = 0.0
    industry_relevance_score: float = 0.0
    support_mode_relevance_score: float = 0.0
    policy_type_relevance_score: float = 0.0
    wrong_region_count: int = 0
    hit_at_k: bool = False
    hit_at_1: bool = False
    passed: bool = False
    failure_reason: Optional[str] = None
    expected_behavior: Optional[str] = None
    profile_name: Optional[str] = None
    top_document_id: Optional[str] = None
    top_title: Optional[str] = None
    top_score: Optional[float] = None
    matched_document_ids: List[str] = Field(default_factory=list)
    retrieved_document_ids: List[str] = Field(default_factory=list)
    ranking: List[RetrievalRankItem] = Field(default_factory=list)
    chunk_anchor_hits: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    notes: Optional[str] = None
    error: Optional[str] = None
    latency_ms: Optional[float] = None


class RetrievalSummary(BaseModel):
    """Aggregate metrics."""

    case_count: int = 0
    answerable_count: int = 0
    negative_count: int = 0
    pass_count: int = 0
    fail_count: int = 0
    error_count: int = 0
    precision_at_k: float = 0.0
    recall_at_k: float = 0.0
    mrr: float = 0.0
    ndcg_at_k: float = 0.0
    chunk_anchor_hit_rate: float = 0.0
    local_priority_score: float = 0.0
    freshness_score: float = 0.0
    industry_relevance_score: float = 0.0
    support_mode_relevance_score: float = 0.0
    policy_type_relevance_score: float = 0.0
    wrong_region_rate: float = 0.0
    weighted_pass_rate: float = 0.0
    route_entry_rate: float = 0.0
    step_by_step_rate: float = 0.0
    service_info_rate: float = 0.0
    need_clarification_rate: float = 0.0
    boundary_refuse_rate: float = 0.0
    hit_at_k_rate: float = 0.0
    hit_at_1_rate: float = 0.0
    no_answer_accuracy: float = 0.0
    golden_count_mismatch_rate: float = 0.0
    latency_ms_avg: float = 0.0
    latency_ms_p50: float = 0.0
    latency_ms_p95: float = 0.0
    latency_ms_max: float = 0.0


class RetrievalReport(BaseModel):
    """Full evaluation report."""

    generated_at: str = Field(default_factory=utc_now_iso)
    namespace: Optional[str] = None
    profile_name: Optional[str] = None
    base_url: str
    cases_path: str
    kb_ids: List[str] = Field(default_factory=list)
    total_documents: int = 0
    summary: RetrievalSummary = Field(default_factory=RetrievalSummary)
    by_behavior: Dict[str, RetrievalSummary] = Field(default_factory=dict)
    by_intent: Dict[str, RetrievalSummary] = Field(default_factory=dict)
    by_priority: Dict[str, RetrievalSummary] = Field(default_factory=dict)
    by_tag: Dict[str, RetrievalSummary] = Field(default_factory=dict)
    cases: List[RetrievalCaseResult] = Field(default_factory=list)
