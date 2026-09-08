"""检索策略公共复用：metadata SQL 下推、召回公共条件、命中组装、rerank 融合、业务信号提取。

各策略文件（vector/weighted/hybrid/keyword/fulltext/keyword_rank）复用本模块的函数，
避免重复。依赖方向：helpers.py → base.py（单向）。

包含四组能力：
1. metadata 过滤下推：把 metadataFilter 的可下推标量条件转成 SQL JSONB 谓词。
2. 召回公共：基础状态过滤 + 预检（省 embedding 调用）。
3. 命中组装与重排：RecallEntry → SearchHit，rerank 开关 + 业务加权融合。
4. 业务信号提取：区域（武汉>湖北>国家）、年份、产业、支持方式、政策文种，对齐评估服务口径。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Set, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.knowledge_service.config import settings
from services.knowledge_service.models import KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from services.knowledge_service.retrieval.base import RecallEntry, SearchContext, SearchHit
from services.knowledge_service.service import metadata_matches, rerank_items


# 顶层嵌套元数据段：metadataFilter 里这三个键会被当作精确路径下钻，而非扁平别名。
_NESTED_SECTIONS = ("common", "domain", "_raw")
# 区域优先级权重（对齐评估服务 runner 的 _region_rank）。
_REGION_RANK = {"武汉": 3, "湖北": 2, "国家": 1}
# 支持方式权重（对企业用户的实际价值：直接资金/税收 > 间接引导 > 其他）。
_SUPPORT_MODE_RANK = {"资金奖补": 1.0, "税费优惠": 0.8, "政策引导": 0.5, "其他": 0.2}
# 政策文种权重（对企业用户的实际重要性：法规/办法/细则 > 措施/方案 > 规划/意见 > 提案/征求意见稿）。
_POLICY_TYPE_RANK = {
    "法律法规": 1.0,
    "管理办法": 0.9,
    "实施细则": 0.9,
    "若干措施": 0.8,
    "实施方案": 0.7,
    "实施意见": 0.6,
    "行动方案": 0.6,
    "发展规划": 0.4,
    "综合文件": 0.3,
    "建议提案": 0.2,
    "征求意见稿": 0.1,
}


# --- 1. metadata 过滤下推 ---

def _json_text_eq(path: List[str], value: Any) -> Any:
    """构造 JSONB 标量相等谓词：metadata_json -> p1 -> ... ->> pn == str(value)。"""
    expression = KnowledgeDocument.metadata_json
    for part in path[:-1]:
        expression = expression.op("->")(part)
    expression = expression.op("->>")(path[-1])
    return expression == str(value)


def _nested_scalars(value: Dict[str, Any], prefix: List[str]) -> List[Tuple[List[str], Any]]:
    """递归收集嵌套段里可下推的标量叶子（str/int/float；list/bool 交给 Python 精筛）。"""
    leaves: List[Tuple[List[str], Any]] = []
    for key, item in value.items():
        if isinstance(item, dict):
            leaves.extend(_nested_scalars(item, prefix + [str(key)]))
        elif isinstance(item, (str, int, float)) and not isinstance(item, bool):
            leaves.append((prefix + [str(key)], item))
    return leaves


def _metadata_sql_conditions(metadata_filter: Dict[str, Any]) -> List[Any]:
    """把 metadataFilter 里可下推的标量条件转成 SQL 谓词（AND 连接）。

    - 嵌套段（common/domain/_raw）下的标量：精确路径相等。
    - 扁平标量 key：OR 匹配 common/domain/_raw 三个路径（对应 metadata_matches 的 aliases 展开）。
    - list/bool 等复杂形态不下推，交由 Python 精筛兜底。
    """
    conditions: List[Any] = []
    for key, value in metadata_filter.items():
        if isinstance(value, dict) and key in _NESTED_SECTIONS:
            for path, scalar in _nested_scalars(value, [key]):
                conditions.append(_json_text_eq(path, scalar))
        elif isinstance(value, (str, int, float)) and not isinstance(value, bool):
            alternatives = [_json_text_eq([section, key], value) for section in _NESTED_SECTIONS]
            conditions.append(or_(*alternatives))
    return conditions


# --- 2. 召回公共 ---

def _base_conditions(ctx: SearchContext) -> List[Any]:
    """检索通道共用的基础过滤条件（kb 范围 / namespace / 状态）。"""
    conditions: List[Any] = [
        KnowledgeBase.status == "active",
        KnowledgeDocument.ingest_status == "completed",
        KnowledgeChunk.status == "active",
    ]
    if ctx.kb_ids:
        conditions.append(KnowledgeBase.id.in_(ctx.kb_ids))
    if ctx.namespace:
        conditions.append(KnowledgeBase.namespace == ctx.namespace)
    return conditions


async def _has_searchable_chunk(session: AsyncSession, ctx: SearchContext) -> bool:
    """预检：无任何可检索分片时返回 False，省一次 embedding 调用。"""
    statement = (
        select(KnowledgeChunk.id)
        .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
        .join(KnowledgeBase, KnowledgeChunk.kb_id == KnowledgeBase.id)
        .where(*_base_conditions(ctx))
        .limit(1)
    )
    searchable_chunk_id = await session.scalar(statement)
    if not searchable_chunk_id:
        return False
    await session.rollback()
    return True


# --- 3. 命中组装与重排 ---

def normalize_score(value: float, scale: float) -> float:
    """把无上界分数 sigmoid 压缩到 (0,1)，保持单调（不改变排序）。

    score = value / (value + scale)。向量相似度（0~1）无需归一化；
    keyword_rank 位置加权分（几十~几百）用 scale=100；fulltext 的 ts_rank 用 scale=1。
    """
    if value <= 0:
        return 0.0
    return value / (value + scale)


def _hit_to_dict(entry: RecallEntry, *, weighted_score: float | None = None) -> SearchHit:
    """把召回条目组装成对外 SearchHit。weighted_score 可选，存业务加权纯 bonus。"""
    chunk, document, kb, raw_distance, score = entry
    hit: SearchHit = {
        "kbId": kb.id,
        "kbName": kb.name,
        "namespace": kb.namespace,
        "documentId": document.id,
        "chunkId": chunk.id,
        "title": document.title,
        "sourceType": document.source_type,
        "sourceRef": document.source_ref,
        "score": round(score, 6),
        "distance": round(raw_distance, 6) if raw_distance is not None else 0.0,
        "contentExcerpt": chunk.content_text[:800],
        "citation": {
            "documentId": document.id,
            "chunkId": chunk.id,
            "title": document.title,
            "sourceRef": document.source_ref,
        },
    }
    if weighted_score is not None:
        hit["weightedScore"] = round(weighted_score, 6)
    return hit


async def _maybe_rerank(ctx: SearchContext, items: List[SearchHit]) -> List[SearchHit]:
    """按 ctx.rerank 决定是否精排：关闭时直接返回，用于延迟敏感场景或评估 rerank 开关影响。"""
    if not ctx.rerank:
        return items
    return await rerank_items(ctx.query, items)


def _fuse_rerank(items: List[SearchHit]) -> List[SearchHit]:
    """把业务加权分（weightedScore 存纯 bonus）融合进精排结果：base + bonus 重排。

    rerank 开启时 base 取 rerankScore（否则取向量 score），再加上业务 bonus。
    这样业务加权不会在 rerank 之后被覆盖——加权是在精排结果上做软偏好微调。
    """
    def fused_score(item: SearchHit) -> float:
        base = item.get("rerankScore") if item.get("rerankScore") is not None else item.get("score", 0.0)
        return float(base) + float(item.get("weightedScore") or 0.0)

    return sorted(items, key=fused_score, reverse=True)


# --- 4. 业务信号提取（对齐评估服务 runner 的口径，但独立实现避免跨服务耦合） ---

def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip())


def _normalize_list(value: Any) -> List[str]:
    if value is None:
        return []
    items = value if isinstance(value, (list, tuple, set)) else [value]
    normalized: List[str] = []
    seen: Set[str] = set()
    for item in items:
        text = _normalize_text(item)
        if text and text not in seen:
            seen.add(text)
            normalized.append(text)
    return normalized


def _metadata_flat(document_metadata: Dict[str, Any]) -> Dict[str, Any]:
    """展平 document.metadata_json 的 _raw/common/domain 为扁平视图（对齐 runner _metadata_view）。"""
    view: Dict[str, Any] = {}
    for key in ("_raw", "common", "domain"):
        value = document_metadata.get(key)
        if isinstance(value, dict):
            view.update(value)
    view.update({key: value for key, value in document_metadata.items() if not str(key).startswith("_")})
    return view


def _normalize_region_label(value: Any) -> str:
    text = _normalize_text(value)
    if "武汉" in text:
        return "武汉"
    if "湖北" in text:
        return "湖北"
    if text in {"国家", "全国", "中央", "国家级"} or "国务院" in text or "中央" in text:
        return "国家"
    return text or "其他"


def _resolve_region(document_metadata: Dict[str, Any]) -> str:
    view = _metadata_flat(document_metadata)
    region = _normalize_text(view.get("region") or view.get("区域"))
    if region:
        return _normalize_region_label(region)
    city = _normalize_text(view.get("city") or view.get("城市"))
    province = _normalize_text(view.get("province") or view.get("省份"))
    if city:
        return "武汉"
    if province:
        return "湖北"
    return "国家"


def _document_year(document_metadata: Dict[str, Any]) -> int | None:
    view = _metadata_flat(document_metadata)
    value = view.get("publishedAt") or view.get("publishTime") or view.get("发布时间")
    match = re.search(r"(19|20)\d{2}", str(value or ""))
    return int(match.group(0)) if match else None


def _document_industry(document_metadata: Dict[str, Any]) -> List[str]:
    view = _metadata_flat(document_metadata)
    value = view.get("industry") or view.get("chain") or view.get("产业分类")
    return _normalize_list(value)


def _document_support_mode(document_metadata: Dict[str, Any]) -> List[str]:
    view = _metadata_flat(document_metadata)
    value = view.get("supportMode") or view.get("支持方式")
    return _normalize_list(value)


def _document_policy_type(document_metadata: Dict[str, Any]) -> str:
    view = _metadata_flat(document_metadata)
    value = view.get("policyDocumentType") or view.get("政策文种")
    return _normalize_text(value)


def _filter_value(metadata_filter: Dict[str, Any], *keys: str) -> Any:
    """从 metadataFilter 取偏好值：先查嵌套段（common/domain/_raw），再查扁平 key。"""
    for section in _NESTED_SECTIONS:
        nested = metadata_filter.get(section)
        if isinstance(nested, dict):
            for key in keys:
                value = nested.get(key)
                if value not in (None, "", [], {}):
                    return value
    for key in keys:
        value = metadata_filter.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _preference_from_filter(metadata_filter: Dict[str, Any]) -> Tuple[str, int | None, Set[str]]:
    """解析加权偏好：region 默认「武汉」，year 默认 None（=最新），industry 默认空集。"""
    region_value = _filter_value(metadata_filter, "region", "区域")
    region = _normalize_region_label(region_value) if region_value else "武汉"

    year_value = _filter_value(metadata_filter, "year", "publishedAt", "publishTime", "发布时间", "年份")
    year: int | None = None
    if year_value is not None:
        match = re.search(r"(19|20)\d{2}", str(year_value))
        if match:
            year = int(match.group(0))

    industry = set(_normalize_list(_filter_value(metadata_filter, "industry", "chain", "产业分类")))
    return region, year, industry


def _weighted_bonus(
    document_metadata: Dict[str, Any],
    region_pref: str,
    reference_year: int | None,
    industry_pref: Set[str],
) -> float:
    """计算文档的业务加权加分（区域 + 时效 + 产业 + 支持方式 + 政策文种）。"""
    bonus = 0.0
    region = _resolve_region(document_metadata)
    bonus += (_REGION_RANK.get(region, 0) / 3.0) * settings.search_region_weight

    if reference_year is not None:
        doc_year = _document_year(document_metadata)
        if doc_year is not None:
            bonus += max(0.0, 1.0 - abs(reference_year - doc_year) / 5.0) * settings.search_freshness_weight

    if industry_pref:
        doc_industry = set(_document_industry(document_metadata))
        if doc_industry & industry_pref:
            bonus += settings.search_industry_weight

    # 支持方式：按对企业用户价值加权（资金奖补 > 税费优惠 > 政策引导 > 其他）
    support_modes = _document_support_mode(document_metadata)
    if support_modes:
        support_rank = max((_SUPPORT_MODE_RANK.get(mode, 0.0) for mode in support_modes), default=0.0)
        bonus += support_rank * settings.search_support_weight

    # 政策文种：按对企业用户重要性加权（法规/办法/细则最高，征求意见稿最低）
    policy_type = _document_policy_type(document_metadata)
    if policy_type:
        bonus += _POLICY_TYPE_RANK.get(policy_type, 0.0) * settings.search_policy_type_weight
    return bonus
