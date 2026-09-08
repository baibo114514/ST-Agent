"""全文检索策略（fulltext，漏斗架构）。

算法：metadata 下推（复用 _metadata_sql_conditions）→ jieba 分词 + PG tsvector/ts_rank
排序 → rerank 精排（可选）。不调用 embedding API。

两层漏斗：
- 第一层：metadata 标量条件下推 SQL（JSONB）。
- 第二层：search_text 列（入库时已用 jieba 分词）的 tsvector 做 @@ 匹配 + ts_rank 排序，
  GIN 表达式索引加速。query 分词后以 OR 语义转 tsquery（避免 AND 召回为 0）。

评估结论（100 条业务场景评估集，单独跑）：
- MRR ~0.88，hit@1 ~0.79，介于 vector 与 keyword 之间。
- jieba 分词 + ts_rank 的词级匹配优于 keyword 的字符 n-gram（word_similarity），
  但排序质量仍不如语义向量（口语化 query 下词级匹配难捕捉语义等价）。
"""

from __future__ import annotations

from typing import List

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.knowledge_service.config import settings
from services.knowledge_service.metadata import tokenize_for_search
from services.knowledge_service.models import KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from services.knowledge_service.retrieval.base import RecallEntry, SearchContext, SearchHit
from services.knowledge_service.retrieval.helpers import (
    _base_conditions,
    _has_searchable_chunk,
    _hit_to_dict,
    _maybe_rerank,
    _metadata_sql_conditions,
    normalize_score,
)
from services.knowledge_service.service import metadata_matches


async def _fulltext_recall(session: AsyncSession, ctx: SearchContext, limit: int) -> List[RecallEntry]:
    """全文检索召回：jieba 分词 + PG tsvector/ts_rank 排序，不调用 embedding API。"""
    tokenized_query = tokenize_for_search(ctx.query)
    if not tokenized_query:
        return []
    words = tokenized_query.split()
    if not words:
        return []
    # OR 语义：任意关键词命中即召回（plainto_tsquery 是 AND，词多时召回为 0）。
    or_query = " | ".join(words)
    tsvector = func.to_tsvector("simple", KnowledgeChunk.search_text)
    tsquery = func.to_tsquery("simple", or_query)
    rank = func.ts_rank(tsvector, tsquery).label("rank")
    conditions = _base_conditions(ctx) + _metadata_sql_conditions(ctx.metadata_filter)
    statement = (
        select(KnowledgeChunk, KnowledgeDocument, KnowledgeBase, rank)
        .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
        .join(KnowledgeBase, KnowledgeChunk.kb_id == KnowledgeBase.id)
        .where(*conditions, tsvector.op("@@")(tsquery))
        .order_by(rank.desc())
        .limit(limit)
    )
    rows = (await session.execute(statement)).all()

    entries: List[RecallEntry] = []
    for chunk, document, kb, raw_rank in rows:
        if not metadata_matches(ctx.metadata_filter, document.metadata_json or {}, chunk.metadata_json or {}):
            continue
        score = normalize_score(float(raw_rank or 0.0), scale=1.0)
        if score < ctx.min_score:
            continue
        entries.append((chunk, document, kb, None, score))
    return entries


class FulltextSearchStrategy:
    """全文检索（漏斗架构）：metadata 下推 + jieba 分词 + PG tsvector/ts_rank，不调用 embedding API。"""

    name = "fulltext"

    async def search(self, session: AsyncSession, ctx: SearchContext) -> List[SearchHit]:
        if not await _has_searchable_chunk(session, ctx):
            return []
        entries = await _fulltext_recall(session, ctx, ctx.top_k * settings.search_oversample_factor)
        items = [_hit_to_dict(entry) for entry in entries]
        reranked = await _maybe_rerank(ctx, items)
        return reranked[: ctx.top_k]
