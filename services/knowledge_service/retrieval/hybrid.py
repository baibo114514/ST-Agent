"""混合检索策略（hybrid，轻量）。

算法：向量召回（复用 vector._vector_recall）→ 对候选做字符 bigram 重叠率加分
（query 关键词在 chunk 正文的命中程度）→ rerank 精排 → 加分融合重排。

设计说明：不做 pg_trgm 全表关键词召回（成本高、收益低），改为对向量召回的候选
在 Python 侧算 bigram 重叠加分，专有名词/政策名等「向量语义易漂移、字符强匹配」
的 query 受益。

评估结论（100 条业务场景评估集，rerank 开）：
- 通过 81/100，MRR 0.856，nDCG 0.884，hit@1 0.771。
- 略优于 vector 的通过数，但 MRR/hit@1 不如 weighted；关键词加分在专有名词场景
  有微弱正收益，整体定位介于 vector 与 weighted 之间。
"""

from __future__ import annotations

from typing import List

from sqlalchemy.ext.asyncio import AsyncSession

from services.knowledge_service.config import settings
from services.knowledge_service.retrieval.base import SearchContext, SearchHit
from services.knowledge_service.retrieval.helpers import (
    _fuse_rerank,
    _has_searchable_chunk,
    _hit_to_dict,
    _maybe_rerank,
    _normalize_text,
)
from services.knowledge_service.retrieval.vector import _vector_recall


def _keyword_bonus(query: str, chunk_text: str) -> float:
    """query 与 chunk 正文的字符 bigram 重叠率（0~1），衡量关键词命中程度。"""
    q = _normalize_text(query)
    text = _normalize_text(chunk_text)
    if not q or len(q) < 2:
        return 0.0
    q_grams = {q[i : i + 2] for i in range(len(q) - 1)}
    if not q_grams:
        return 0.0
    text_grams = {text[i : i + 2] for i in range(len(text) - 1)}
    return len(q_grams & text_grams) / len(q_grams)


class HybridSearchStrategy:
    """混合检索（轻量）：向量召回 + 关键词加分 +（可选）rerank 融合。

    实例通过 `rerank` 区分是否精排：`hybrid`（不重排）与 `hybrid_reranker`（重排）。
    当策略显式指定 rerank 时覆盖请求级 rerank 布尔（算法名优先）。
    """

    def __init__(self, rerank: bool = False) -> None:
        self.rerank = rerank
        self.name = "hybrid_reranker" if rerank else "hybrid"

    async def search(self, session: AsyncSession, ctx: SearchContext) -> List[SearchHit]:
        if not await _has_searchable_chunk(session, ctx):
            return []
        ctx.rerank = self.rerank
        entries = await _vector_recall(session, ctx, ctx.top_k * settings.search_oversample_factor)
        if not entries:
            return []

        items: List[SearchHit] = []
        for entry in entries:
            chunk = entry[0]
            overlap = _keyword_bonus(ctx.query, chunk.content_text)
            bonus = overlap * settings.search_keyword_weight
            items.append(_hit_to_dict(entry, weighted_score=bonus))

        reranked = await _maybe_rerank(ctx, items)
        fused = _fuse_rerank(reranked)
        return fused[: ctx.top_k]
