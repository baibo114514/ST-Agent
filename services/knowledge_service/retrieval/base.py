"""检索策略基础层：类型定义、请求上下文、策略接口与注册表。

本模块是检索算法子包 `retrieval/` 的公共基础，不包含任何具体检索逻辑。
各策略文件（vector/weighted/hybrid/keyword/fulltext/keyword_rank）依赖本模块
的 `SearchContext` / `SearchHit` / `SearchStrategy` 与注册表，单向依赖、无循环。

对外契约：`POST /internal/v1/kb/search` 的请求体会被 `SearchContext.from_payload`
归一化，检索结果以 `SearchHit`（camelCase 字段）列表返回。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Protocol, Tuple, TypedDict

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from services.knowledge_service.models import KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from services.knowledge_service.service import problem


class SearchHit(TypedDict, total=False):
    """单条检索命中项，字段与对外契约（camelCase）一致。

    各字段含义：
    - score：最终排序分。向量/关键词相似度为 0~1；keyword_rank 为「位置加权分」
      （量纲几十~几百，见 keyword_rank.py 说明）。
    - distance：向量距离（仅向量类策略有意义，关键词类为 0）。
    - rerankScore：rerank 精排分（仅开启 rerank 时有）。
    - weightedScore：业务加权增量（weighted/hybrid 策略的纯 bonus）。
    - rawScore：keyword_rank 的位置加权原始分（未乘规则 multiplier）。
    """

    kbId: str
    kbName: str
    namespace: str
    documentId: str
    chunkId: str
    title: str
    sourceType: str
    sourceRef: str | None
    score: float
    distance: float
    contentExcerpt: str
    rerankScore: float | None
    weightedScore: float | None
    rawScore: float | None
    citation: Dict[str, Any]


@dataclass(slots=True)
class SearchContext:
    """一次检索请求的归一化上下文。"""

    query: str
    kb_ids: List[str]
    top_k: int
    min_score: float
    metadata_filter: Dict[str, Any]
    namespace: str | None
    strategy: str | None = None
    rerank: bool = True

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "SearchContext":
        query = str(payload.get("query") or "").strip()
        if not query:
            raise problem(status.HTTP_400_BAD_REQUEST, "INVALID_QUERY", "query is required")
        top_k = max(1, min(int(payload.get("topK") or payload.get("top_k") or 5), 20))
        min_score = float(payload.get("minScore") or payload.get("scoreThreshold") or 0)

        kb_ids = payload.get("kbIds") or payload.get("kb_ids") or []
        single_kb_id = payload.get("kbId") or payload.get("kb_id")
        if single_kb_id and not kb_ids:
            kb_ids = [single_kb_id]
        if kb_ids is None:
            kb_ids = []
        if not isinstance(kb_ids, list):
            raise problem(status.HTTP_400_BAD_REQUEST, "INVALID_KB_IDS", "kbIds must be an array")

        metadata_filter = payload.get("metadataFilter") or {}
        if not isinstance(metadata_filter, dict):
            raise problem(status.HTTP_400_BAD_REQUEST, "INVALID_METADATA_FILTER", "metadataFilter must be an object")

        namespace = payload.get("namespace")
        strategy = payload.get("strategy")
        rerank = bool(payload.get("rerank", True))
        return cls(
            query=query,
            kb_ids=[str(kb_id) for kb_id in kb_ids],
            top_k=top_k,
            min_score=min_score,
            metadata_filter=metadata_filter,
            namespace=str(namespace) if namespace else None,
            strategy=str(strategy).strip().lower() if strategy else None,
            rerank=rerank,
        )


class SearchStrategy(Protocol):
    """检索策略接口。新算法只需实现 `name` 与 `search()` 并注册。"""

    name: str

    async def search(self, session: AsyncSession, ctx: SearchContext) -> List[SearchHit]: ...


STRATEGIES: Dict[str, SearchStrategy] = {}


def register_strategy(strategy: SearchStrategy) -> None:
    """注册检索策略（按 name 索引）。"""
    STRATEGIES[strategy.name] = strategy


def get_strategy(name: str) -> SearchStrategy | None:
    return STRATEGIES.get(name)


# 召回条目：(chunk, document, kb, distance, score)。distance 对关键词类通道为 None。
RecallEntry = Tuple[KnowledgeChunk, KnowledgeDocument, KnowledgeBase, float | None, float]
