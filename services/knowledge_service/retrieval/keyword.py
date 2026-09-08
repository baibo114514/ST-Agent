"""纯关键词检索策略（keyword）。

算法：pg_trgm word_similarity 排序（GIN trigram 索引加速）→ metadata 过滤 →
rerank 精排（可选）。不调用 embedding API。

用 word_similarity 而非 similarity：它取 query 中最相似的词片段与 chunk 比对，
短 query 对长文本时更合理（similarity 对整句 query 会因长度差异把分数压到接近 0）。

评估结论（100 条业务场景评估集，rerank 开）：
- 通过 86/100，MRR 0.880，nDCG 0.900，hit@1 0.792，recall@k 0.967。
- 无嵌入基线：recall 不低（字符匹配能召回含关键词的文档），但排序质量明显弱于
  vector/weighted（hit@1 低 ~10 个点）；且 word_similarity 全表扫，延迟反而高
  （~1.9s，因 trigram 索引不加速相似度排序）。
"""

from __future__ import annotations

from typing import List

from sqlalchemy import func, select
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
from services.knowledge_service.service import metadata_matches


async def _keyword_recall(session: AsyncSession, ctx: SearchContext, limit: int) -> List[RecallEntry]:
    """纯关键词召回：pg_trgm word_similarity 排序（GIN trigram 索引加速），不调用 embedding API。"""
    similarity = func.word_similarity(ctx.query, KnowledgeChunk.content_text)
    conditions = _base_conditions(ctx) + _metadata_sql_conditions(ctx.metadata_filter)
    statement = (
        select(KnowledgeChunk, KnowledgeDocument, KnowledgeBase, similarity.label("similarity"))
        .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
        .join(KnowledgeBase, KnowledgeChunk.kb_id == KnowledgeBase.id)
        .where(*conditions, similarity >= settings.hybrid_similarity_threshold)
        .order_by(similarity.desc())
        .limit(limit)
    )
    rows = (await session.execute(statement)).all()

    entries: List[RecallEntry] = []
    for chunk, document, kb, sim in rows:
        if not metadata_matches(ctx.metadata_filter, document.metadata_json or {}, chunk.metadata_json or {}):
            continue
        score = float(sim or 0.0)
        if score < ctx.min_score:
            continue
        entries.append((chunk, document, kb, None, score))
    return entries


class KeywordSearchStrategy:
    """纯关键词检索：pg_trgm similarity 召回，不调用 embedding API，作无嵌入基线对比。"""

    name = "keyword"

    async def search(self, session: AsyncSession, ctx: SearchContext) -> List[SearchHit]:
        if not await _has_searchable_chunk(session, ctx):
            return []
        entries = await _keyword_recall(session, ctx, ctx.top_k * settings.search_oversample_factor)
        items = [_hit_to_dict(entry) for entry in entries]
        reranked = await _maybe_rerank(ctx, items)
        return reranked[: ctx.top_k]
