"""元数据加权排序策略（weighted）。

算法：向量召回（复用 vector._vector_recall）→ 按业务软偏好加分（区域/时效/产业，
固定规则 + metadataFilter 覆盖）→ 叠加「支持方式 / 政策文种」对企业用户的内在重要性
加权 → rerank 精排 → 加权分融合重排。

关键点：业务加权分以「纯 bonus」形式存入 weightedScore，rerank 之后用
`_fuse_rerank` 按 `base + bonus` 重排——这样加权不会被 rerank 覆盖，而是在精排
结果上做软偏好微调。

评估结论（100 条业务场景评估集，rerank 开）：
- 通过 86/100，MRR 0.931，nDCG 0.926，hit@1 0.906，local_priority 0.887。
- **六策略中精度最优**：在向量分之上叠加区域/时效软偏好，MRR 比 vector 高 +7.9%、
  hit@1 高 +16%。
"""

from __future__ import annotations

from typing import List

from sqlalchemy.ext.asyncio import AsyncSession

from services.knowledge_service.config import settings
from services.knowledge_service.retrieval.base import SearchContext, SearchHit
from services.knowledge_service.retrieval.helpers import (
    _document_year,
    _fuse_rerank,
    _has_searchable_chunk,
    _hit_to_dict,
    _maybe_rerank,
    _preference_from_filter,
    _weighted_bonus,
)
from services.knowledge_service.retrieval.vector import _vector_recall


class WeightedVectorSearchStrategy:
    """元数据加权排序：向量召回后按业务软偏好（区域/时效/产业）加分，（可选）rerank 后融合重排。

    实例通过 `rerank` 区分是否精排：`weighted`（不重排）与 `weighted_reranker`（重排）。
    当策略显式指定 rerank 时覆盖请求级 rerank 布尔（算法名优先）。
    """

    def __init__(self, rerank: bool = False) -> None:
        self.rerank = rerank
        self.name = "weighted_reranker" if rerank else "weighted"

    async def search(self, session: AsyncSession, ctx: SearchContext) -> List[SearchHit]:
        if not await _has_searchable_chunk(session, ctx):
            return []
        ctx.rerank = self.rerank
        entries = await _vector_recall(session, ctx, ctx.top_k * settings.search_oversample_factor)
        if not entries:
            return []

        region_pref, year_pref, industry_pref = _preference_from_filter(ctx.metadata_filter)
        years = [year for entry in entries if (year := _document_year(entry[1].metadata_json or {})) is not None]
        reference_year = year_pref or (max(years) if years else None)

        # weightedScore 存纯业务 bonus，供 _fuse_rerank 在 rerank 后融合。
        items: List[SearchHit] = []
        for entry in entries:
            bonus = _weighted_bonus(entry[1].metadata_json or {}, region_pref, reference_year, industry_pref)
            items.append(_hit_to_dict(entry, weighted_score=bonus))

        reranked = await _maybe_rerank(ctx, items)
        fused = _fuse_rerank(reranked)
        return fused[: ctx.top_k]
