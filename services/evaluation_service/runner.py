"""检索评估核心 runner。

黑盒评测 knowledge-service 的检索质量：给定用例（RetrievalCase）里的 query 与
检索请求，调用内部检索接口拿到返回列表，再与用例声明的 ground truth（文档 id /
标题 / 源引用 / 元数据过滤）比对，逐条计算文档级、片段级与业务级指标，最后汇总
成 RetrievalReport 落盘。

评测口径（详见 retrieval_eval_design.md）：
- 文档级：Recall@K / MRR / nDCG@K / Hit@K / Hit@1。
- 片段级：chunkAnchors 命中率（返回片段是否含关键锚点）。
- 业务级：本地优先（武汉 > 湖北 > 国家）、时效（年份越新越好）、产业相关性、错区域惩罚、负例拒答。
- 速度级：单次检索端到端延迟（latency_ms），汇总 avg / p50 / p95 / max。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import defaultdict
from math import log2
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Sequence

from services.evaluation_service.client import KnowledgeServiceClient, KnowledgeServiceError
from services.evaluation_service.profiles import EvaluationProfile, infer_namespace_label_from_path, resolve_profile
from services.evaluation_service.report import write_report_files
from services.evaluation_service.schemas import (
    KnowledgeDocumentRecord,
    KnowledgeSearchItem,
    RetrievalCase,
    RetrievalCaseResult,
    RetrievalRankItem,
    RetrievalReport,
    RetrievalSummary,
)
from services.evaluation_service.settings import RetrievalEvalConfig


logger = logging.getLogger("evaluation_service")

FILTER_INTENTS = {"区域", "政策类型", "支持方式", "政策文种", "部门", "产业分类"}
GOLDEN_RESERVED_KEYS = {
    "docIds",
    "documentIds",
    "doc_ids",
    "document_ids",
    "chunkAnchors",
    "chunk_anchors",
    "filters",
    "relevanceGrades",
    "relevance_grades",
    "titles",
    "sourceRefs",
    "source_refs",
}


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip())


def _normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        items = value
    elif isinstance(value, (tuple, set)):
        items = list(value)
    else:
        items = [value]
    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _normalize_text(item)
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
    return normalized


def _normalize_region_label(value: Any) -> str:
    """把任意区域表述归一为「武汉 / 湖北 / 国家 / 其他」四档。"""
    text = _normalize_text(value)
    if "武汉" in text:
        return "武汉"
    if "湖北" in text:
        return "湖北"
    if text in {"国家", "全国", "中央", "国家级"} or "国务院" in text or "中央" in text:
        return "国家"
    return text or "其他"


def _resolve_region(metadata: Dict[str, Any]) -> str:
    """从文档元数据解析区域标签，缺省按国家处理。"""
    view = _metadata_view(metadata)
    region = _normalize_text(view.get("region") or view.get("区域"))
    if region:
        return _normalize_region_label(region)
    city = _normalize_text(view.get("city") or view.get("城市"))
    province = _normalize_text(view.get("province") or view.get("省份"))
    place = _normalize_text(view.get("place") or view.get("地区"))
    if city:
        return "武汉"
    if province:
        return "湖北"
    if place:
        return "湖北" if place else "国家"
    return "国家"


def _metadata_view(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Expose canonical and legacy policy keys to the existing eval corpus."""
    view: Dict[str, Any] = {}
    for key in ("_raw", "common", "domain"):
        value = metadata.get(key)
        if isinstance(value, dict):
            view.update(value)
    view.update({key: value for key, value in metadata.items() if not str(key).startswith("_")})
    if "industry" in view and "chain" not in view:
        view["chain"] = view["industry"]
    if "department" in view and "dept" not in view:
        view["dept"] = view["department"]
    if "policyType" in view and "policyTypeName" not in view:
        view["policyTypeName"] = view["policyType"]
    if "supportMode" in view and "supportmodeName" not in view:
        view["supportmodeName"] = view["supportMode"]
    if "policyDocumentType" in view and "政策文种" not in view:
        view["政策文种"] = view["policyDocumentType"]
    return view


def metadata_subset(expected: Any, actual: Any) -> bool:
    """判断 expected 是否 actual 的（递归）子集：dict 逐键递归，list 逐元素包含，标量相等。"""
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        return all(key in actual and metadata_subset(value, actual[key]) for key, value in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and all(item in actual for item in expected)
    return expected == actual


def _match_expected_value(actual: Any, expected: Any) -> bool:
    """宽松匹配元数据字段值：期望为集合则看交集，标量则看相等或包含（归一化后）。"""
    if isinstance(expected, (list, tuple, set)):
        expected_values = {_normalize_text(item) for item in expected if _normalize_text(item)}
        if not expected_values:
            return False
        if isinstance(actual, (list, tuple, set)):
            actual_values = {_normalize_text(item) for item in actual if _normalize_text(item)}
            return bool(actual_values & expected_values)
        actual_text = _normalize_text(actual)
        return actual_text in expected_values

    expected_text = _normalize_text(expected)
    if isinstance(actual, (list, tuple, set)):
        return expected_text in {_normalize_text(item) for item in actual if _normalize_text(item)}
    actual_text = _normalize_text(actual)
    if not actual_text:
        return False
    return actual_text == expected_text or expected_text in actual_text


def _match_ground_truth_text(
    actual: Any,
    expected: Any,
    *,
    allow_partial: bool = False,
) -> bool:
    """匹配文档标题 / 源引用。

    policy 仍保留严格精确匹配；service / generic profile 允许前后缀与包含匹配，
    以兼容知识库里带有库名前缀或相对路径的标题展示。
    """
    actual_text = _normalize_text(actual)
    expected_text = _normalize_text(expected)
    if not actual_text or not expected_text:
        return False
    if actual_text == expected_text:
        return True
    if not allow_partial:
        return False
    return actual_text.endswith(expected_text) or expected_text in actual_text or actual_text in expected_text


def document_matches_filter(document: KnowledgeDocumentRecord, golden: Dict[str, Any]) -> bool:
    """判断文档是否满足 golden 里声明的元数据过滤条件。

    golden 中除保留键（docIds/titles/chunkAnchors 等）外的键都视为过滤条件；
    区域/部门/产业/政策类型/支持方式/文种等字段有专门的归一化匹配逻辑。
    """
    metadata = document.metadata_json or {}
    view = _metadata_view(metadata)
    title = _normalize_text(document.title or view.get("title"))
    for key, expected in _golden_filters(golden).items():
        if expected in (None, "", [], {}, ()):
            continue

        if key in {"_schema", "common", "domain", "_raw"}:
            if not isinstance(metadata.get(key), dict) or not metadata_subset({key: expected}, metadata):
                return False
            continue

        if key in {"区域", "region"}:
            if not _match_expected_value(_resolve_region(metadata), expected):
                return False
            continue
        if key in {"部门", "dept"}:
            actual = view.get("dept") or view.get("部门") or view.get("department") or []
            if not _match_expected_value(actual, expected):
                return False
            continue
        if key in {"产业分类", "chain"}:
            actual = view.get("chain") or view.get("产业分类") or []
            if not _match_expected_value(actual, expected):
                return False
            continue
        if key in {"政策类型", "policyTypeName"}:
            actual = view.get("policyTypeName") or view.get("政策类型") or view.get("type")
            if not _match_expected_value(actual, expected):
                return False
            continue
        if key in {"支持方式", "supportmodeName"}:
            actual = view.get("supportmodeName") or view.get("支持方式")
            if not _match_expected_value(actual, expected):
                return False
            continue
        if key in {"政策文种", "policyDocumentType", "docType", "typeName"}:
            actual = (
                view.get("政策文种")
                or view.get("policyDocumentType")
                or view.get("docType")
                or view.get("typeName")
                or title
            )
            if not _match_expected_value(actual, expected):
                return False
            continue

        actual = view.get(key)
        if actual is None:
            actual = title
        if not _match_expected_value(actual, expected):
            return False
    return True


def _golden_filters(golden: Dict[str, Any]) -> Dict[str, Any]:
    """取出 golden 里的过滤条件：优先读 filters 键，否则取排除保留键后的其余字段。"""
    filters = golden.get("filters")
    if isinstance(filters, dict):
        return filters
    return {key: value for key, value in golden.items() if key not in GOLDEN_RESERVED_KEYS}


def _golden_document_ids(case: RetrievalCase) -> list[str]:
    ids = list(case.golden_document_ids)
    if not ids and isinstance(case.golden, dict):
        raw_ids = (
            case.golden.get("docIds")
            or case.golden.get("documentIds")
            or case.golden.get("doc_ids")
            or case.golden.get("document_ids")
            or []
        )
        ids = _normalize_list(raw_ids)
    return ids


def _golden_chunk_anchors(case: RetrievalCase) -> list[str]:
    if case.chunk_anchors:
        return case.chunk_anchors
    if isinstance(case.golden, dict):
        return _normalize_list(case.golden.get("chunkAnchors") or case.golden.get("chunk_anchors"))
    return []


def _golden_titles(case: RetrievalCase) -> list[str]:
    if case.golden_titles:
        return case.golden_titles
    return _normalize_list(case.golden.get("titles")) if isinstance(case.golden, dict) else []


def _golden_source_refs(case: RetrievalCase) -> list[str]:
    if case.golden_source_refs:
        return case.golden_source_refs
    if isinstance(case.golden, dict):
        return _normalize_list(case.golden.get("sourceRefs") or case.golden.get("source_refs"))
    return []


def _case_request(case: RetrievalCase) -> Dict[str, Any]:
    return case.request if isinstance(case.request, dict) else {}


def _metadata_value(metadata: Dict[str, Any], *paths: str) -> Any:
    """按点分路径（如 common.publishedAt）依次取元数据值，支持 flat 键回退（走 _metadata_view）。"""
    for path in paths:
        current: Any = metadata
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                current = None
                break
            current = current[part]
        if current not in (None, "", [], {}):
            return current
    view = _metadata_view(metadata)
    for path in paths:
        if path in view and view[path] not in (None, "", [], {}):
            return view[path]
    return None


def _request_value(request: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = request.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _document_year(document: KnowledgeDocumentRecord) -> int | None:
    """从文档元数据的发布日期字段提取 4 位年份，取不到返回 None。"""
    value = _metadata_value(document.metadata_json or {}, "common.publishedAt", "publishedAt", "publishTime", "发布时间")
    match = re.search(r"(19|20)\d{2}", str(value or ""))
    return int(match.group(0)) if match else None


def _document_support_mode(document: KnowledgeDocumentRecord) -> list[str]:
    """从文档元数据提取支持方式（资金奖补/税费优惠/政策引导/其他）。"""
    value = _metadata_value(
        document.metadata_json or {},
        "domain.supportMode", "supportMode", "supportmodeName", "支持方式",
    )
    return _normalize_list(value)


def _document_policy_type(document: KnowledgeDocumentRecord) -> str:
    """从文档元数据提取政策文种（管理办法/实施细则/若干措施等）。"""
    value = _metadata_value(
        document.metadata_json or {},
        "domain.policyDocumentType", "policyDocumentType", "政策文种",
    )
    return _normalize_text(value)


def _scenario_value(case: RetrievalCase, *keys: str) -> Any:
    for source in (case.scenario, _case_request(case)):
        for key in keys:
            value = source.get(key) if isinstance(source, dict) else None
            if value not in (None, "", [], {}):
                return value
    return None


def _golden_value(case: RetrievalCase, *keys: str) -> Any:
    filters = _golden_filters(case.golden)
    for key in keys:
        if filters.get(key) not in (None, "", [], {}):
            return filters[key]
    return None


def _search_request(case: RetrievalCase, default_kb_ids: Sequence[str], config: RetrievalEvalConfig) -> Dict[str, Any]:
    """组装检索请求体：kbIds / topK / scoreThreshold 依次取用例 request → 用例字段 → 全局配置。"""
    request = _case_request(case)
    kb_ids = _request_value(request, "kbIds", "kb_ids") or case.kb_ids or list(default_kb_ids)
    namespace = _request_value(request, "namespace")
    if namespace in (None, "", [], {}):
        namespace = config.namespace
    return {
        "kb_ids": _normalize_list(kb_ids),
        "top_k": int(_request_value(request, "topK", "top_k") or case.top_k or config.top_k),
        "score_threshold": float(
            _request_value(request, "scoreThreshold", "score_threshold", "minScore", "min_score")
            if _request_value(request, "scoreThreshold", "score_threshold", "minScore", "min_score") is not None
            else case.score_threshold if case.score_threshold is not None else config.score_threshold
        ),
        "metadata_filter": _request_value(request, "metadataFilter", "metadata_filter") or {},
        "namespace": namespace,
        "strategy": config.strategy or _request_value(request, "strategy"),
        "rerank": _request_value(request, "rerank"),
    }


def _quality_requirements(case: RetrievalCase, config: RetrievalEvalConfig) -> Dict[str, float]:
    """取业务级指标阈值：允许用例 request 覆盖全局配置的本地/时效/锚点/产业/负例阈值。"""
    request = _case_request(case)
    return {
        "local": float(request.get("localPriorityThreshold", config.local_priority_threshold)),
        "freshness": float(request.get("freshnessThreshold", config.freshness_threshold)),
        "anchors": float(request.get("chunkAnchorThreshold", config.chunk_anchor_threshold)),
        "industry": float(request.get("industryRelevanceThreshold", config.industry_relevance_threshold)),
        "support_mode": float(request.get("supportModeRelevanceThreshold", config.support_mode_relevance_threshold)),
        "policy_type": float(request.get("policyTypeRelevanceThreshold", config.policy_type_relevance_threshold)),
        "negative_max_score": float(request.get("negativeMaxScore", config.negative_max_score)),
    }


def _service_quality_requirements(case: RetrievalCase, config: RetrievalEvalConfig) -> Dict[str, float]:
    """客服/通用类用例的轻量质量阈值：只保留锚点与负例拒答阈值。"""
    request = _case_request(case)
    return {
        "anchors": float(request.get("chunkAnchorThreshold", config.chunk_anchor_threshold)),
        "negative_max_score": float(request.get("negativeMaxScore", config.negative_max_score)),
    }


def _normalized_behavior(case: RetrievalCase) -> str:
    return _normalize_text(case.expected_behavior).lower()


def _behavior_bucket(behavior: str | None) -> str:
    normalized = _normalize_text(behavior).lower()
    if not normalized:
        return "unknown"
    return normalized


def dedupe_search_items(items: Sequence[KnowledgeSearchItem]) -> list[KnowledgeSearchItem]:
    """按 documentId 去重，保留首次出现的检索结果。"""
    seen: set[str] = set()
    unique: list[KnowledgeSearchItem] = []
    for item in items:
        if item.document_id in seen:
            continue
        seen.add(item.document_id)
        unique.append(item)
    return unique


def load_cases(path: Path, case_ids: set[str] | None = None, limit: int | None = None) -> list[RetrievalCase]:
    """读取 JSONL 用例文件。

    每行一条 JSON；跳过空行与 `#` 注释行；兼容 snake_case 字段名（case_id/kb_ids/
    top_k/score_threshold 等）并归一为 camelCase；支持按 case_ids 过滤与 limit 截断。
    """
    if not path.is_file():
        raise FileNotFoundError(f"cases file not found: {path}")

    selected_ids = {item.strip() for item in (case_ids or set()) if item.strip()}
    cases: list[RetrievalCase] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            raw = json.loads(line)
            if "case_id" in raw and "id" not in raw:
                raw["id"] = raw["case_id"]
            if "kb_ids" in raw and "kbIds" not in raw:
                raw["kbIds"] = raw["kb_ids"]
            if "top_k" in raw and "topK" not in raw:
                raw["topK"] = raw["top_k"]
            if "score_threshold" in raw and "scoreThreshold" not in raw:
                raw["scoreThreshold"] = raw["score_threshold"]
            if "golden_document_ids" in raw and "goldenDocumentIds" not in raw:
                raw["goldenDocumentIds"] = raw["golden_document_ids"]
            if "golden_titles" in raw and "goldenTitles" not in raw:
                raw["goldenTitles"] = raw["golden_titles"]
            if "golden_source_refs" in raw and "goldenSourceRefs" not in raw:
                raw["goldenSourceRefs"] = raw["golden_source_refs"]
            if "expected_behavior" in raw and "expectedBehavior" not in raw:
                raw["expectedBehavior"] = raw["expected_behavior"]
            case = RetrievalCase.model_validate(raw)
            if selected_ids and case.case_id not in selected_ids:
                continue
            cases.append(case)
            if limit is not None and len(cases) >= limit:
                break
    return cases


async def build_catalog(
    client: KnowledgeServiceClient,
    kb_ids: Sequence[str],
    page_size: int,
) -> dict[str, KnowledgeDocumentRecord]:
    """遍历知识库的文档列表接口，按 documentId 建全量目录索引，供 ground truth 解析与指标打分用。"""
    catalog: dict[str, KnowledgeDocumentRecord] = {}
    for kb_id in kb_ids:
        page = 1
        total_pages = 1
        while page <= total_pages:
            payload = await client.list_documents(kb_id, page=page, page_size=page_size)
            documents = client.parse_documents(payload)
            for document in documents:
                catalog[document.document_id] = document
            total_pages = int(payload.get("totalPages") or 0) or 1
            if payload.get("totalPages") in (0, None):
                break
            page += 1
    return catalog


def resolve_ground_truth_ids(
    case: RetrievalCase,
    catalog: dict[str, KnowledgeDocumentRecord],
    profile: EvaluationProfile | None = None,
) -> tuple[list[str], int]:
    """把用例声明的 ground truth 解析成目录里的 documentId 列表。

    三种定位方式按优先级：显式 docIds > 标题/源引用匹配 > 元数据过滤匹配。
    返回 (id 列表, 期望命中数)。
    """
    explicit_ids = _golden_document_ids(case)
    if explicit_ids:
        ids = []
        for doc_id in explicit_ids:
            normalized = str(doc_id).strip()
            if normalized:
                ids.append(normalized)
        return ids, len(ids)

    allow_partial_match = not (profile and profile.apply_policy_gates)
    titles = _golden_titles(case)
    source_refs = _golden_source_refs(case)
    if titles or source_refs:
        matched = []
        for doc_id, document in catalog.items():
            if titles and any(
                _match_ground_truth_text(document.title, title, allow_partial=allow_partial_match)
                for title in titles
            ):
                matched.append(doc_id)
                continue
            if source_refs and any(
                _match_ground_truth_text(document.source_ref, value, allow_partial=allow_partial_match)
                for value in source_refs
            ):
                matched.append(doc_id)
        return matched, len(matched)

    expected_filter = case.golden or _request_value(_case_request(case), "metadataFilter", "metadata_filter") or {}
    if expected_filter:
        matched = [doc_id for doc_id, document in catalog.items() if document_matches_filter(document, expected_filter)]
        return matched, len(matched)

    return [], 0


def _evaluate_service_docs(
    *,
    case: RetrievalCase,
    retrieved_items: Sequence[KnowledgeSearchItem],
    ground_truth_ids: Sequence[str],
    catalog: Dict[str, KnowledgeDocumentRecord] | None = None,
    quality_requirements: Dict[str, float] | None = None,
    profile: EvaluationProfile | None = None,
    entry_strict_hit_at_1: bool = True,
) -> RetrievalCaseResult:
    """客服/通用类检索评估：按行为类型区分入口、流程、事实与澄清类样本。"""
    profile = profile or resolve_profile("service")
    unique_items = dedupe_search_items(retrieved_items)
    retrieved_ids = [item.document_id for item in unique_items]
    golden_set = set(ground_truth_ids)
    matched_ids = [doc_id for doc_id in retrieved_ids if doc_id in golden_set]
    hit_at_k = bool(matched_ids)
    hit_at_1 = bool(unique_items and unique_items[0].document_id in golden_set)
    matched_count = len(matched_ids)
    retrieved_count = len(unique_items)
    golden_count = len(golden_set)
    precision = matched_count / retrieved_count if retrieved_count else 0.0
    recall = matched_count / golden_count if golden_count else 0.0
    first_hit_rank = next(
        (index + 1 for index, item in enumerate(unique_items) if item.document_id in golden_set),
        None,
    )
    mrr = 1.0 / first_hit_rank if first_hit_rank else 0.0
    top_item = unique_items[0] if unique_items else None
    catalog = catalog or {}
    ndcg = _ndcg_at_k(unique_items, case, golden_set, catalog)
    anchor_hits = _chunk_anchor_hits(retrieved_items, _golden_chunk_anchors(case))
    quality_requirements = quality_requirements or {
        "anchors": 1.0,
        "negative_max_score": 0.35,
    }
    expected_behavior = _normalized_behavior(case)

    ranking = []
    for index, item in enumerate(unique_items):
        document = catalog.get(item.document_id)
        ranking.append(
            RetrievalRankItem(
                rank=index + 1,
                document_id=item.document_id,
                title=item.title,
                score=item.score,
                region=_resolve_region(document.metadata_json) if document else None,
                published_year=_document_year(document) if document else None,
                matched=item.document_id in golden_set,
            )
        )

    quality_failures: list[str] = []
    if _golden_chunk_anchors(case) and (
        len(anchor_hits) / len(_golden_chunk_anchors(case)) < quality_requirements["anchors"]
    ):
        quality_failures.append("CHUNK_ANCHOR_COVERAGE_LOW")

    refusal_expected = expected_behavior in {"need_clarification", "boundary_refuse"}
    if not case.answerable or refusal_expected:
        passed = retrieved_count == 0 or bool(top_item and top_item.score < quality_requirements["negative_max_score"])
        failure_reason = None if passed else "SHOULD_NOT_MATCH"
    elif expected_behavior == "route_entry":
        passed = hit_at_1 if entry_strict_hit_at_1 else hit_at_k
        failure_reason = None if passed else "NO_GOLDEN_DOC_HIT"
    else:
        passed = hit_at_k
        failure_reason = None if passed else "NO_GOLDEN_HIT"

    if passed and quality_failures:
        passed = False
        failure_reason = quality_failures[0]

    return RetrievalCaseResult(
        case_id=case.case_id,
        intent=case.intent,
        query=case.query,
        answerable=case.answerable,
        priority=case.priority,
        golden_count_expected=case.golden_count,
        golden_count_actual=golden_count,
        retrieved_count=retrieved_count,
        matched_count=matched_count,
        precision_at_k=round(precision, 6),
        recall_at_k=round(recall, 6),
        mrr=round(mrr, 6),
        ndcg_at_k=round(ndcg, 6),
        chunk_anchor_hit_rate=round(
            len(anchor_hits) / len(_golden_chunk_anchors(case)), 6
        ) if _golden_chunk_anchors(case) else 0.0,
        local_priority_score=0.0,
        freshness_score=0.0,
        industry_relevance_score=0.0,
        support_mode_relevance_score=0.0,
        policy_type_relevance_score=0.0,
        wrong_region_count=0,
        hit_at_k=hit_at_k,
        hit_at_1=hit_at_1,
        passed=passed,
        failure_reason=failure_reason,
        expected_behavior=case.expected_behavior,
        profile_name=profile.name,
        top_document_id=top_item.document_id if top_item else None,
        top_title=top_item.title if top_item else None,
        top_score=top_item.score if top_item else None,
        matched_document_ids=matched_ids,
        retrieved_document_ids=retrieved_ids,
        ranking=ranking,
        chunk_anchor_hits=anchor_hits,
        tags=case.tags,
        notes=case.notes,
    )


def evaluate_retrieved_docs(
    *,
    case: RetrievalCase,
    retrieved_items: Sequence[KnowledgeSearchItem],
    ground_truth_ids: Sequence[str],
    catalog: Dict[str, KnowledgeDocumentRecord] | None = None,
    quality_requirements: Dict[str, float] | None = None,
    profile: EvaluationProfile | None = None,
) -> RetrievalCaseResult:
    """对单条用例的检索结果打分，产出 RetrievalCaseResult。

    计算文档级（precision/recall/MRR/nDCG/Hit@K/Hit@1）、片段级（锚点命中）、
    业务级（本地优先/时效/产业相关性/错区域）指标，再按用例意图判定 pass/fail：

    - 负例（answerable=False）：期望不返回或首位低分；
    - golden 文档未进目录：判定失败（GOLDEN_DOCUMENT_NOT_IN_CATALOG）；
    - 元数据过滤意图（区域/政策类型等）：要求 Hit@1 且 precision≥0.6；
    - 其余：Hit@K 即通过。
    通过后若触发质量门槛（本地/时效/产业阈值不达标），改判失败并记录原因。
    """
    profile = profile or resolve_profile("policy")
    if not profile.apply_policy_gates:
        return _evaluate_service_docs(
            case=case,
            retrieved_items=retrieved_items,
            ground_truth_ids=ground_truth_ids,
            catalog=catalog,
            quality_requirements=quality_requirements,
            profile=profile,
            entry_strict_hit_at_1=profile.positive_hit_mode == "hit_at_1",
        )

    unique_items = dedupe_search_items(retrieved_items)
    retrieved_ids = [item.document_id for item in unique_items]
    matched_ids = [doc_id for doc_id in retrieved_ids if doc_id in set(ground_truth_ids)]
    hit_at_k = bool(matched_ids)
    hit_at_1 = bool(unique_items and unique_items[0].document_id in set(ground_truth_ids))
    matched_count = len(matched_ids)
    retrieved_count = len(unique_items)
    golden_count = len(set(ground_truth_ids))
    precision = matched_count / retrieved_count if retrieved_count else 0.0
    recall = matched_count / golden_count if golden_count else 0.0
    first_hit_rank = next(
        (index + 1 for index, item in enumerate(unique_items) if item.document_id in set(ground_truth_ids)),
        None,
    )
    mrr = 1.0 / first_hit_rank if first_hit_rank else 0.0
    top_item = unique_items[0] if unique_items else None
    catalog = catalog or {}
    golden_set = set(ground_truth_ids)
    ndcg = _ndcg_at_k(unique_items, case, golden_set, catalog)
    anchor_hits = _chunk_anchor_hits(retrieved_items, _golden_chunk_anchors(case))
    expected_region = _expected_region(case)
    local_priority_score = _local_priority_score(unique_items, case, catalog, expected_region)
    freshness_score = _freshness_score(unique_items, case, catalog)
    industry_relevance_score = _industry_relevance_score(unique_items, case, catalog)
    support_mode_relevance_score = _support_mode_relevance_score(unique_items, case, catalog)
    policy_type_relevance_score = _policy_type_relevance_score(unique_items, case, catalog)
    wrong_region_count = _wrong_region_count(unique_items, case, catalog, expected_region)
    ranking = []
    for index, item in enumerate(unique_items):
        document = catalog.get(item.document_id)
        ranking.append(
            RetrievalRankItem(
                rank=index + 1,
                document_id=item.document_id,
                title=item.title,
                score=item.score,
                region=_resolve_region(document.metadata_json) if document else None,
                published_year=_document_year(document) if document else None,
                matched=item.document_id in golden_set,
            )
        )

    quality_requirements = quality_requirements or {
        "local": 0.8,
        "freshness": 0.8,
        "anchors": 1.0,
        "industry": 0.7,
        "support_mode": 0.7,
        "policy_type": 0.7,
        "negative_max_score": 0.35,
    }
    quality_failures: list[str] = []
    if _golden_chunk_anchors(case) and (
        len(anchor_hits) / len(_golden_chunk_anchors(case)) < quality_requirements["anchors"]
    ):
        quality_failures.append("CHUNK_ANCHOR_COVERAGE_LOW")
    behavior = _normalize_text(case.expected_behavior).lower()
    if any(token in behavior for token in ("local", "region_priority", "prefer_local", "本地优先", "区域优先")) and (
        local_priority_score < quality_requirements["local"]
    ):
        quality_failures.append("LOCAL_PRIORITY_LOW")
    if any(token in behavior for token in ("fresh", "time_priority", "prefer_latest", "最新", "时效")) and (
        freshness_score < quality_requirements["freshness"]
    ):
        quality_failures.append("FRESHNESS_LOW")
    if any(token in behavior for token in ("industry", "industry_priority", "产业优先")) and (
        industry_relevance_score < quality_requirements["industry"]
    ):
        quality_failures.append("INDUSTRY_RELEVANCE_LOW")
    if any(token in behavior for token in ("support_mode", "supportmode", "支持方式")) and (
        support_mode_relevance_score < quality_requirements["support_mode"]
    ):
        quality_failures.append("SUPPORT_MODE_RELEVANCE_LOW")
    if any(token in behavior for token in ("policy_type", "policy_document_type", "政策文种")) and (
        policy_type_relevance_score < quality_requirements["policy_type"]
    ):
        quality_failures.append("POLICY_TYPE_RELEVANCE_LOW")

    if not case.answerable:
        passed = retrieved_count == 0 or bool(top_item and top_item.score < quality_requirements["negative_max_score"])
        failure_reason = None if passed else "SHOULD_NOT_MATCH"
    elif not golden_set and (_golden_document_ids(case) or _golden_titles(case) or _golden_source_refs(case)):
        passed = False
        failure_reason = "GOLDEN_DOCUMENT_NOT_IN_CATALOG"
    elif _golden_document_ids(case):
        passed = hit_at_k
        failure_reason = None if passed else "NO_GOLDEN_DOC_HIT"
    elif case.intent in FILTER_INTENTS:
        passed = hit_at_1 and precision >= 0.6
        failure_reason = None if passed else "FILTER_QUALITY_LOW"
    else:
        passed = hit_at_k
        failure_reason = None if passed else "NO_GOLDEN_HIT"
    if passed and quality_failures:
        passed = False
        failure_reason = quality_failures[0]

    return RetrievalCaseResult(
        case_id=case.case_id,
        intent=case.intent,
        query=case.query,
        answerable=case.answerable,
        priority=case.priority,
        golden_count_expected=case.golden_count,
        golden_count_actual=golden_count,
        retrieved_count=retrieved_count,
        matched_count=matched_count,
        precision_at_k=round(precision, 6),
        recall_at_k=round(recall, 6),
        mrr=round(mrr, 6),
        ndcg_at_k=round(ndcg, 6),
        chunk_anchor_hit_rate=round(
            len(anchor_hits) / len(_golden_chunk_anchors(case)), 6
        ) if _golden_chunk_anchors(case) else 0.0,
        local_priority_score=round(local_priority_score, 6),
        freshness_score=round(freshness_score, 6),
        industry_relevance_score=round(industry_relevance_score, 6),
        support_mode_relevance_score=round(support_mode_relevance_score, 6),
        policy_type_relevance_score=round(policy_type_relevance_score, 6),
        wrong_region_count=wrong_region_count,
        hit_at_k=hit_at_k,
        hit_at_1=hit_at_1,
        passed=passed,
        failure_reason=failure_reason,
        expected_behavior=case.expected_behavior,
        profile_name=profile.name,
        top_document_id=top_item.document_id if top_item else None,
        top_title=top_item.title if top_item else None,
        top_score=top_item.score if top_item else None,
        matched_document_ids=matched_ids,
        retrieved_document_ids=retrieved_ids,
        ranking=ranking,
        chunk_anchor_hits=anchor_hits,
        tags=case.tags,
        notes=case.notes,
    )


def _ndcg_at_k(
    items: Sequence[KnowledgeSearchItem],
    case: RetrievalCase,
    golden_ids: set[str],
    catalog: Dict[str, KnowledgeDocumentRecord],
) -> float:
    """计算 nDCG@K。文档相关性等级：显式 relevanceGrades > golden 命中=1.0 > 元数据过滤匹配=1.0 > 其余=0.0。"""
    configured_grades = case.relevance_grades or {}
    if not configured_grades and isinstance(case.golden, dict):
        configured_grades = case.golden.get("relevanceGrades") or case.golden.get("relevance_grades") or {}

    def grade(document_id: str) -> float:
        if document_id in configured_grades:
            return float(configured_grades[document_id])
        if document_id in golden_ids:
            return 1.0
        golden_filter = _golden_filters(case.golden)
        if golden_filter and document_id in catalog:
            return 1.0 if document_matches_filter(catalog[document_id], golden_filter) else 0.0
        return 0.0

    actual = sum((2**grade(item.document_id) - 1) / log2(index + 2) for index, item in enumerate(items))
    ideal_grades = sorted(
        (grade(document_id) for document_id in catalog),
        reverse=True,
    )[: len(items)]
    ideal = sum((2**value - 1) / log2(index + 2) for index, value in enumerate(ideal_grades))
    return actual / ideal if ideal else 0.0


def _chunk_anchor_hits(items: Sequence[KnowledgeSearchItem], anchors: Sequence[str]) -> list[str]:
    """返回在任意检索结果的 contentExcerpt 中命中的锚点列表（归一化后子串匹配）。"""
    hits = []
    excerpts = [_normalize_text(item.content_excerpt) for item in items]
    for anchor in anchors:
        normalized = _normalize_text(anchor)
        if normalized and any(normalized in excerpt for excerpt in excerpts):
            hits.append(str(anchor))
    return hits


def _expected_region(case: RetrievalCase) -> str | None:
    """推断用例期望的区域：优先 scenario/golden 显式声明，否则按预期行为（本地优先）默认武汉。"""
    explicit = _scenario_value(case, "region", "区域")
    explicit = explicit or _golden_value(case, "region", "区域")
    if explicit:
        return _normalize_region_label(explicit)
    behavior = _normalize_text(case.expected_behavior)
    if "local" in behavior or "武汉" in behavior or not explicit:
        return "武汉"
    return None


def _region_rank(value: str) -> int:
    """区域优先级权重：武汉(3) > 湖北(2) > 国家(1) > 其他(0)。"""
    return {"武汉": 3, "湖北": 2, "国家": 1}.get(value, 0)


def _item_region(item: KnowledgeSearchItem, catalog: Dict[str, KnowledgeDocumentRecord]) -> str:
    document = catalog.get(item.document_id)
    return _resolve_region(document.metadata_json) if document else "其他"


def _local_priority_score(
    items: Sequence[KnowledgeSearchItem],
    case: RetrievalCase,
    catalog: Dict[str, KnowledgeDocumentRecord],
    expected_region: str | None,
) -> float:
    """本地优先得分（0~1），软偏好口径。

    按区域权重比例给分：命中目标区域（武汉>湖北>国家）得满分，低一档按 rank/target_rank
    折减（湖北相对武汉 0.67，国家 0.33），不再要求「必须全是对应区域」的硬匹配——
    prefer_local 语义是「优先本地」而非「只允许本地」。log 折扣位置加权求和。
    """
    if not items or not expected_region:
        return 0.0
    available = max((_region_rank(_resolve_region(document.metadata_json)) for document in catalog.values()), default=0)
    target_rank = _region_rank(expected_region)
    if available < target_rank:
        target_rank = available
    scores = []
    for item in items:
        rank = _region_rank(_item_region(item, catalog))
        scores.append(1.0 if rank == target_rank else max(0.0, min(1.0, rank / max(target_rank, 1))))
    return sum(score / log2(index + 2) for index, score in enumerate(scores)) / sum(
        1 / log2(index + 2) for index in range(len(scores))
    )


def _freshness_score(
    items: Sequence[KnowledgeSearchItem],
    case: RetrievalCase,
    catalog: Dict[str, KnowledgeDocumentRecord],
) -> float:
    """时效得分（0~1）。以用例期望年份或返回结果最新年份为基准，每差一年扣 0.2（5 年线性衰减），
    再以 log 折扣位置加权求和。"""
    if not items:
        return 0.0
    expected_year = _scenario_value(case, "year", "publishYear", "publishedYear", "年份")
    expected_year = expected_year or _golden_value(case, "year", "publishYear", "publishedYear", "年份")
    try:
        target_year = int(expected_year) if expected_year else None
    except (TypeError, ValueError):
        target_year = None
    years = [_document_year(catalog[item.document_id]) for item in items if item.document_id in catalog]
    years = [year for year in years if year is not None]
    if not years:
        return 0.0
    reference_year = target_year or max(years)
    scores = [max(0.0, min(1.0, 1.0 - abs(reference_year - (year or reference_year)) / 5)) for year in years]
    return sum(score / log2(index + 2) for index, score in enumerate(scores)) / sum(
        1 / log2(index + 2) for index in range(len(scores))
    )


def _wrong_region_count(
    items: Sequence[KnowledgeSearchItem],
    case: RetrievalCase,
    catalog: Dict[str, KnowledgeDocumentRecord],
    expected_region: str | None,
) -> int:
    """统计返回结果里「区域不对」的条数：显式区域时按不等于期望区域计，否则按权重低于期望档位计。"""
    if not expected_region:
        return 0
    expected_rank = _region_rank(expected_region)
    explicit_region = _scenario_value(case, "region", "区域") or _golden_value(case, "region", "区域")
    if explicit_region:
        return sum(1 for item in items if _item_region(item, catalog) != expected_region)
    return sum(1 for item in items if _region_rank(_item_region(item, catalog)) < expected_rank - 1)


def _industry_relevance_score(
    items: Sequence[KnowledgeSearchItem],
    case: RetrievalCase,
    catalog: Dict[str, KnowledgeDocumentRecord],
) -> float:
    """产业相关性得分（0~1）。用例声明目标产业时，按每条结果是否命中该产业给分并位置加权。"""
    expected = _scenario_value(case, "industry", "产业分类") or _golden_value(case, "industry", "产业分类")
    expected_values = _normalize_list(expected)
    if not items or not expected_values:
        return 0.0
    scores = []
    for item in items:
        document = catalog.get(item.document_id)
        actual = _metadata_value(document.metadata_json, "domain.industry", "industry", "chain", "产业分类") if document else None
        scores.append(1.0 if _match_expected_value(actual, expected_values) else 0.0)
    return sum(score / log2(index + 2) for index, score in enumerate(scores)) / sum(
        1 / log2(index + 2) for index in range(len(scores))
    )


def _support_mode_relevance_score(
    items: Sequence[KnowledgeSearchItem],
    case: RetrievalCase,
    catalog: Dict[str, KnowledgeDocumentRecord],
) -> float:
    """支持方式相关性得分（0~1）。用例声明目标支持方式（如资金奖补）时，
    按每条结果是否命中该支持方式给分并位置加权。"""
    expected = _scenario_value(case, "支持方式", "supportMode") or _golden_value(case, "支持方式", "supportMode")
    expected_values = _normalize_list(expected)
    if not items or not expected_values:
        return 0.0
    scores = []
    for item in items:
        document = catalog.get(item.document_id)
        actual = _document_support_mode(document) if document else []
        scores.append(1.0 if _match_expected_value(actual, expected_values) else 0.0)
    return sum(score / log2(index + 2) for index, score in enumerate(scores)) / sum(
        1 / log2(index + 2) for index in range(len(scores))
    )


def _policy_type_relevance_score(
    items: Sequence[KnowledgeSearchItem],
    case: RetrievalCase,
    catalog: Dict[str, KnowledgeDocumentRecord],
) -> float:
    """政策文种相关性得分（0~1）。用例声明目标文种（如管理办法）时，
    按每条结果是否命中该文种给分并位置加权。"""
    expected = _scenario_value(case, "政策文种", "policyDocumentType") or _golden_value(case, "政策文种", "policyDocumentType")
    expected_values = _normalize_list(expected)
    if not items or not expected_values:
        return 0.0
    scores = []
    for item in items:
        document = catalog.get(item.document_id)
        actual = _document_policy_type(document) if document else ""
        scores.append(1.0 if _match_expected_value(actual, expected_values) else 0.0)
    return sum(score / log2(index + 2) for index, score in enumerate(scores)) / sum(
        1 / log2(index + 2) for index in range(len(scores))
    )


def _case_weight(priority: int) -> int:
    """Priority 1 is highest business importance and therefore gets most weight."""
    return max(1, 4 - priority)


def _percentile(values: Sequence[float], pct: float) -> float:
    """返回 values 的 pct 分位数（0~100）。用最近秩法，空序列返回 0.0。"""
    sorted_values = sorted(value for value in values if value is not None)
    if not sorted_values:
        return 0.0
    rank = int(round(pct / 100.0 * (len(sorted_values) - 1)))
    return float(sorted_values[rank])


def aggregate_summary(results: Sequence[RetrievalCaseResult]) -> RetrievalSummary:
    """把逐条结果汇总成全局指标：各项文档级/业务级得分取均值，负例单独算 no_answer_accuracy，
    pass 率按 priority 加权（priority 1 权重最高）。"""
    if not results:
        return RetrievalSummary()

    answerable_results = [item for item in results if item.answerable]
    negative_results = [item for item in results if not item.answerable]
    success_results = [item for item in results if item.passed]
    failure_results = [item for item in results if not item.passed and not item.error]
    error_results = [item for item in results if item.error]

    def _mean(values: Sequence[float]) -> float:
        values = [value for value in values if value is not None]
        return round(mean(values), 6) if values else 0.0

    total_weight = sum(_case_weight(result.priority) for result in results)
    weighted_pass_rate = (
        sum(_case_weight(result.priority) for result in results if result.passed)
        / total_weight
        if total_weight
        else 0.0
    )

    latencies = [item.latency_ms for item in results if item.latency_ms is not None]

    def _behavior_rate(*labels: str, use_hit_at_1: bool = False) -> float:
        normalized = {_behavior_bucket(label) for label in labels if _behavior_bucket(label)}
        selected = [item for item in results if _behavior_bucket(item.expected_behavior) in normalized]
        if not selected:
            return 0.0
        if use_hit_at_1:
            values = [1.0 if item.hit_at_1 else 0.0 for item in selected]
        else:
            values = [1.0 if item.passed else 0.0 for item in selected]
        return _mean(values)

    return RetrievalSummary(
        case_count=len(results),
        answerable_count=len(answerable_results),
        negative_count=len(negative_results),
        pass_count=len(success_results),
        fail_count=len(failure_results),
        error_count=len(error_results),
        precision_at_k=_mean([item.precision_at_k for item in answerable_results]),
        recall_at_k=_mean([item.recall_at_k for item in answerable_results]),
        mrr=_mean([item.mrr for item in answerable_results]),
        ndcg_at_k=_mean([item.ndcg_at_k for item in answerable_results]),
        chunk_anchor_hit_rate=_mean([item.chunk_anchor_hit_rate for item in answerable_results]),
        local_priority_score=_mean([item.local_priority_score for item in answerable_results]),
        freshness_score=_mean([item.freshness_score for item in answerable_results]),
        industry_relevance_score=_mean([item.industry_relevance_score for item in answerable_results]),
        support_mode_relevance_score=_mean([item.support_mode_relevance_score for item in answerable_results]),
        policy_type_relevance_score=_mean([item.policy_type_relevance_score for item in answerable_results]),
        wrong_region_rate=(
            round(sum(item.wrong_region_count for item in answerable_results) / sum(item.retrieved_count for item in answerable_results), 6)
            if sum(item.retrieved_count for item in answerable_results)
            else 0.0
        ),
        weighted_pass_rate=round(weighted_pass_rate, 6),
        route_entry_rate=_behavior_rate("route_entry", use_hit_at_1=True),
        step_by_step_rate=_behavior_rate("step_by_step"),
        service_info_rate=_behavior_rate("service_info"),
        need_clarification_rate=_behavior_rate("need_clarification"),
        boundary_refuse_rate=_behavior_rate("boundary_refuse"),
        hit_at_k_rate=_mean([1.0 if item.hit_at_k else 0.0 for item in answerable_results]),
        hit_at_1_rate=_mean([1.0 if item.hit_at_1 else 0.0 for item in answerable_results]),
        no_answer_accuracy=_mean([1.0 if item.passed else 0.0 for item in negative_results]),
        golden_count_mismatch_rate=_mean([1.0 if item.golden_count_expected != item.golden_count_actual else 0.0 for item in results if item.golden_count_expected is not None]),
        latency_ms_avg=round(mean(latencies), 3) if latencies else 0.0,
        latency_ms_p50=round(_percentile(latencies, 50), 3),
        latency_ms_p95=round(_percentile(latencies, 95), 3),
        latency_ms_max=round(max(latencies), 3) if latencies else 0.0,
    )


def group_by_intent(results: Sequence[RetrievalCaseResult]) -> dict[str, RetrievalSummary]:
    grouped: dict[str, list[RetrievalCaseResult]] = defaultdict(list)
    for item in results:
        grouped[item.intent or "unknown"].append(item)
    return {intent: aggregate_summary(items) for intent, items in grouped.items()}


def group_by_behavior(results: Sequence[RetrievalCaseResult]) -> dict[str, RetrievalSummary]:
    grouped: dict[str, list[RetrievalCaseResult]] = defaultdict(list)
    for item in results:
        grouped[_behavior_bucket(item.expected_behavior)].append(item)
    return {behavior: aggregate_summary(items) for behavior, items in grouped.items()}


def group_by_priority(results: Sequence[RetrievalCaseResult]) -> dict[str, RetrievalSummary]:
    grouped: dict[str, list[RetrievalCaseResult]] = defaultdict(list)
    for item in results:
        grouped[str(item.priority)].append(item)
    return {priority: aggregate_summary(items) for priority, items in grouped.items()}


def group_by_tag(results: Sequence[RetrievalCaseResult]) -> dict[str, RetrievalSummary]:
    grouped: dict[str, list[RetrievalCaseResult]] = defaultdict(list)
    for item in results:
        for tag in item.tags:
            grouped[tag].append(item)
    return {tag: aggregate_summary(items) for tag, items in grouped.items()}


def _collect_kb_ids(cases: Sequence[RetrievalCase], config: RetrievalEvalConfig) -> list[str]:
    """汇总 default_kb_ids 与用例声明的 kb_ids，去重保序。"""
    case_kb_ids: list[str] = []
    for case in cases:
        case_kb_ids.extend(case.kb_ids)
        case_kb_ids.extend(_normalize_list(_request_value(_case_request(case), "kbIds", "kb_ids")))
    kb_ids = list(dict.fromkeys([*config.default_kb_ids, *case_kb_ids]))
    if not kb_ids:
        raise ValueError("no knowledge base ids configured; set EVAL_KB_IDS or add kbIds to cases")
    return kb_ids


async def prepare_retrieval_catalog(config: RetrievalEvalConfig) -> dict[str, KnowledgeDocumentRecord]:
    """加载用例并构建文档目录索引（与检索策略无关，可跨多策略复用）。

    目录只需建一次：策略只影响 search 阶段，目录仅用于 ground truth 解析与打分。
    复用目录可避免每个策略重复分页拉取全部文档、触发知识库服务限流（429）。
    """
    cases = load_cases(config.cases_path, case_ids=set(config.case_ids), limit=config.limit)
    if not cases:
        raise ValueError(f"no retrieval cases loaded from {config.cases_path}")
    kb_ids = _collect_kb_ids(cases, config)
    client = KnowledgeServiceClient(config)
    try:
        catalog = await build_catalog(client, kb_ids, config.document_page_size)
    finally:
        await client.aclose()
    logger.info("retrieval_catalog_loaded kb_ids=%s documents=%s", kb_ids, len(catalog))
    return catalog


async def run_retrieval_eval(
    config: RetrievalEvalConfig,
    *,
    catalog: dict[str, KnowledgeDocumentRecord] | None = None,
) -> RetrievalReport:
    """评测主流程：加载用例 → 收集知识库 → 建目录 → 逐条检索+打分 → 汇总 → 写报告。

    请求按信号量串行（默认并发 1，配合 request_interval_seconds 限流）；单条失败降级为
    REQUEST_ERROR 结果而不是中断整个评测。传入 catalog 可复用预先构建的目录（多策略跑分）。
    """
    if not config.knowledge_service_token:
        raise ValueError("EVAL_KNOWLEDGE_SERVICE_TOKEN or KNOWLEDGE_SERVICE_TOKEN is required")

    cases = load_cases(config.cases_path, case_ids=set(config.case_ids), limit=config.limit)
    if not cases:
        raise ValueError(f"no retrieval cases loaded from {config.cases_path}")

    namespace_label = config.namespace or infer_namespace_label_from_path(config.cases_path)
    config.namespace = namespace_label
    profile = resolve_profile(namespace_label)

    kb_ids = _collect_kb_ids(cases, config)

    client = KnowledgeServiceClient(config)
    semaphore = asyncio.Semaphore(1)
    try:
        if catalog is None:
            catalog = await build_catalog(client, kb_ids, config.document_page_size)
        logger.info("retrieval_catalog_loaded kb_ids=%s documents=%s", kb_ids, len(catalog))

        results: list[RetrievalCaseResult] = []
        for case in cases:
            search_request = _search_request(case, kb_ids, config)
            current_kb_ids = search_request["kb_ids"] or list(config.default_kb_ids) or kb_ids
            try:
                started = time.perf_counter()
                async with semaphore:
                    retrieved_items = await client.search(
                        query=case.query,
                        kb_ids=current_kb_ids,
                        top_k=search_request["top_k"],
                        score_threshold=search_request["score_threshold"],
                        metadata_filter=search_request["metadata_filter"],
                        namespace=search_request["namespace"],
                        strategy=search_request["strategy"],
                        rerank=search_request["rerank"],
                        trace_id=f"eval-{case.case_id}",
                    )
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                selected_catalog = {doc_id: doc for doc_id, doc in catalog.items() if doc.kb_id in current_kb_ids}
                ground_truth_ids, expected_count = resolve_ground_truth_ids(case, selected_catalog, profile)
                result = evaluate_retrieved_docs(
                    case=case,
                    retrieved_items=retrieved_items,
                    ground_truth_ids=ground_truth_ids,
                    catalog=selected_catalog,
                    quality_requirements=(
                        _quality_requirements(case, config)
                        if profile.apply_policy_gates
                        else _service_quality_requirements(case, config)
                    ),
                    profile=profile,
                )
                result.latency_ms = round(elapsed_ms, 3)
                if case.golden_count is not None and expected_count != case.golden_count:
                    result.golden_count_actual = expected_count
                results.append(result)
                logger.info(
                    "retrieval_case_completed case_id=%s intent=%s passed=%s retrieved_count=%s matched_count=%s",
                    case.case_id,
                    case.intent,
                    result.passed,
                    result.retrieved_count,
                    result.matched_count,
                )
            except KnowledgeServiceError as exc:
                logger.exception("retrieval_case_failed case_id=%s error=%s", case.case_id, exc)
                results.append(
                    RetrievalCaseResult(
                        case_id=case.case_id,
                        intent=case.intent,
                        query=case.query,
                        answerable=case.answerable,
                        priority=case.priority,
                        golden_count_expected=case.golden_count,
                        retrieved_count=0,
                        passed=False,
                        failure_reason="REQUEST_ERROR",
                        error=str(exc),
                        tags=case.tags,
                        notes=case.notes,
                    )
                )
            await asyncio.sleep(max(0.0, config.request_interval_seconds))
    finally:
        await client.aclose()

    report = RetrievalReport(
        base_url=config.knowledge_service_base_url,
        cases_path=str(config.cases_path),
        namespace=profile.namespace,
        profile_name=profile.name,
        kb_ids=kb_ids,
        total_documents=len(catalog),
        summary=aggregate_summary(results),
        by_behavior=group_by_behavior(results),
        by_intent=group_by_intent(results),
        by_priority=group_by_priority(results),
        by_tag=group_by_tag(results),
        cases=results,
    )
    if config.generate_report:
        write_report_files(report, config.output_dir)
    logger.info(
        "retrieval_eval_completed cases=%s passed=%s failed=%s errors=%s output_dir=%s",
        len(results),
        report.summary.pass_count,
        report.summary.fail_count,
        report.summary.error_count,
        config.output_dir,
    )
    return report
