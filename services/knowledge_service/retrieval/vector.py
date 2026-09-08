"""纯向量检索策略（vector）。

算法：HNSW 向量召回（pgvector cosine_distance 排序）→ metadata SQL 粗筛 →
Python 精筛（复杂 metadata 形态兜底）→ min_score 过滤 → rerank 精排（可选）。

依赖 embedding API（query → bge-m3 向量），是唯一「语义」检索通道。

评估结论（100 条业务场景评估集，rerank 开）：
- 通过 80/100，MRR 0.863，nDCG 0.884，hit@1 0.781，recall@k 0.950。
- 是加权/混合等策略的基线；语义召回质量稳定，排序弱于 weighted（后者叠加业务偏好）。
"""

from __future__ import annotations

from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.knowledge_service.config import settings
from services.knowledge_service.models import KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from services.knowledge_service.retrieval.base import RecallEntry, SearchContext, SearchHit
from services.knowledge_service.retrieval.helpers import (
    _base_conditions,
    _has_searchable_chunk,
    _hit_to_dict,
    _maybe_rerank,
    _metadata_sql_conditions,
)
from services.knowledge_service.service import get_embedding, metadata_matches


async def _vector_recall(session: AsyncSession, ctx: SearchContext, limit: int) -> List[RecallEntry]:
    """向量召回：HNSW cosine_distance 排序，metadata SQL 粗筛 + Python 精筛 + min_score。"""
    query_vector = await get_embedding(ctx.query)
    distance = KnowledgeChunk.embedding.cosine_distance(query_vector).label("distance")
    conditions = _base_conditions(ctx) + _metadata_sql_conditions(ctx.metadata_filter)
    statement = (
        select(KnowledgeChunk, KnowledgeDocument, KnowledgeBase, distance)
        .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
        .join(KnowledgeBase, KnowledgeChunk.kb_id == KnowledgeBase.id)
        .where(*conditions)
        .order_by(distance)
        .limit(limit)
    )
    rows = (await session.execute(statement)).all()

    entries: List[RecallEntry] = []
    for chunk, document, kb, raw_distance in rows:
        if not metadata_matches(ctx.metadata_filter, document.metadata_json or {}, chunk.metadata_json or {}):
            continue
        score = max(0.0, 1.0 - float(raw_distance or 0.0))
        if score < ctx.min_score:
            continue
        entries.append((chunk, document, kb, float(raw_distance or 0.0), score))
    return entries


class VectorSearchStrategy:
    """纯向量检索：HNSW 召回 + metadata 粗筛 + Python 精筛 +（可选）rerank。

    实例通过 `rerank` 区分是否精排：`vector`（不重排）与 `vector_reranker`（重排）。
    当策略显式指定 rerank 时覆盖请求级 rerank 布尔（算法名优先）。
    """

    def __init__(self, rerank: bool = False) -> None:
        self.rerank = rerank
        self.name = "vector_reranker" if rerank else "vector"

    async def search(self, session: AsyncSession, ctx: SearchContext) -> List[SearchHit]:
        if not await _has_searchable_chunk(session, ctx):
            return []
        ctx.rerank = self.rerank
        entries = await _vector_recall(session, ctx, ctx.top_k * settings.search_oversample_factor)
        items = [_hit_to_dict(entry) for entry in entries]
        reranked = await _maybe_rerank(ctx, items)
        return reranked[: ctx.top_k]
