"""检索算法子包：可插拔检索策略 + 分发器。

把检索从 service.py 里抽成可插拔策略：`search()` 是薄分发器，根据请求里的
`strategy` 字段（缺省走配置的默认策略）查找并调用对应的 `SearchStrategy`。
新增算法只需在独立文件里实现 `SearchStrategy` 并在此注册，便于多种算法 A/B 评估。

目录结构（每算法一文件，含算法说明与评估结果）：
- base.py          基础层：SearchHit / SearchContext / SearchStrategy / 注册表
- helpers.py       公共复用：metadata 下推 / 召回条件 / 命中组装 / 业务信号
- vector.py        纯向量检索
- weighted.py      元数据加权排序
- hybrid.py        混合检索（向量 + 关键词加分）
- keyword.py       纯关键词检索（pg_trgm）
- fulltext.py      全文检索（jieba + tsvector）
- keyword_rank.py  关键词评分 + 规则重排（移植自 agent-paas）
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.knowledge_service.config import settings
from services.knowledge_service.models import KnowledgeBase
from services.knowledge_service.retrieval.base import (
    SearchContext,
    get_strategy,
    register_strategy,
)
from services.knowledge_service.retrieval.fulltext import FulltextSearchStrategy
from services.knowledge_service.retrieval.hybrid import HybridSearchStrategy
from services.knowledge_service.retrieval.keyword import KeywordSearchStrategy
from services.knowledge_service.retrieval.keyword_rank import KeywordRankSearchStrategy
from services.knowledge_service.retrieval.vector import VectorSearchStrategy
from services.knowledge_service.retrieval.weighted import WeightedVectorSearchStrategy
from services.knowledge_service.service import problem

# 注册所有检索策略（按 name 索引，请求 strategy 字段据此查找）。
# 向量类策略区分「是否 rerank」：无后缀=不重排，`_reranker` 后缀=重排；
# 无嵌入策略（keyword/fulltext/keyword_rank）不提供 rerank 变体。
register_strategy(VectorSearchStrategy(rerank=False))
register_strategy(VectorSearchStrategy(rerank=True))
register_strategy(WeightedVectorSearchStrategy(rerank=False))
register_strategy(WeightedVectorSearchStrategy(rerank=True))
register_strategy(HybridSearchStrategy(rerank=False))
register_strategy(HybridSearchStrategy(rerank=True))
register_strategy(KeywordSearchStrategy())
register_strategy(FulltextSearchStrategy())
register_strategy(KeywordRankSearchStrategy())


async def _resolve_strategy_name(session: AsyncSession, ctx: SearchContext) -> str:
    """解析本次检索使用的策略名。

    优先级：请求显式 strategy > 单 kb 的 searchPolicyJson.strategy > 全局默认。
    多 kb 场景（无法确定单一算法）直接回退全局默认，保持行为可预期。
    """
    if ctx.strategy:
        return ctx.strategy
    if len(ctx.kb_ids) == 1:
        kb = await session.scalar(select(KnowledgeBase).where(KnowledgeBase.id == ctx.kb_ids[0]))
        policy = kb.search_policy_json if kb else None
        configured = policy.get("strategy") if isinstance(policy, dict) else None
        if configured:
            return str(configured).strip().lower()
    return settings.default_search_strategy


async def _resolve_allow_web_fallback(session: AsyncSession, ctx: SearchContext) -> bool:
    """解析是否允许联网兜底：命中范围内任一知识库配置了 allowWebFallback 即为 True。

    默认 False（保守），需知识库显式开启。知识库级开关存于 searchPolicyJson.allowWebFallback。
    """
    if not ctx.kb_ids:
        return False
    kbs = (await session.execute(select(KnowledgeBase).where(KnowledgeBase.id.in_(ctx.kb_ids)))).scalars().all()
    return any(
        isinstance(kb.search_policy_json, dict) and bool(kb.search_policy_json.get("allowWebFallback"))
        for kb in kbs
    )


async def search(session: AsyncSession, payload: Dict[str, Any]) -> Dict[str, Any]:
    """检索分发器：解析请求 → 选策略 → 执行 → 返回 items + allowWebFallback。"""
    ctx = SearchContext.from_payload(payload)
    strategy_name = await _resolve_strategy_name(session, ctx)
    strategy = get_strategy(strategy_name)
    if strategy is None:
        raise problem(
            status.HTTP_400_BAD_REQUEST,
            "UNKNOWN_STRATEGY",
            f"unknown search strategy: {strategy_name}",
        )
    hits = await strategy.search(session, ctx)
    allow_web_fallback = await _resolve_allow_web_fallback(session, ctx)
    return {"items": hits, "total": len(hits), "allowWebFallback": allow_web_fallback}


__all__ = ["search", "get_strategy", "register_strategy", "SearchContext"]
