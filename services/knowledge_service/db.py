"""
Knowledge-service 数据库连接。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

from services.knowledge_service.config import settings
from services.knowledge_service.models import (
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeIngestJob,
    KnowledgeIngestStep,
)


engine = create_async_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_timeout=settings.database_pool_timeout,
)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
KNOWLEDGE_MODEL_TYPES = (
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeIngestJob,
    KnowledgeIngestStep,
)


async def init_database() -> None:
    async with engine.begin() as connection:
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await connection.run_sync(SQLModel.metadata.create_all)
        await connection.execute(
            text(
                "ALTER TABLE te_knowledge_base "
                "ADD COLUMN IF NOT EXISTS metadata_extraction_json JSON NOT NULL DEFAULT '{}'"
            )
        )
        # metadata 过滤下推依赖 JSONB（@> 包含 / ? 数组元素）。已有库的 metadata_json 是 json
        # 类型，这里幂等升级为 jsonb；新库由 create_all 直接建 jsonb，本块跳过。
        await connection.execute(
            text(
                "DO $$ "
                "BEGIN "
                "IF EXISTS (SELECT 1 FROM information_schema.columns "
                "           WHERE table_name = 'te_knowledge_document' "
                "             AND column_name = 'metadata_json' AND data_type = 'json') THEN "
                "  ALTER TABLE te_knowledge_document ALTER COLUMN metadata_json TYPE jsonb USING metadata_json::jsonb; "
                "END IF; "
                "IF EXISTS (SELECT 1 FROM information_schema.columns "
                "           WHERE table_name = 'td_knowledge_chunk' "
                "             AND column_name = 'metadata_json' AND data_type = 'json') THEN "
                "  ALTER TABLE td_knowledge_chunk ALTER COLUMN metadata_json TYPE jsonb USING metadata_json::jsonb; "
                "END IF; "
                "END $$;"
            )
        )
        # 向量检索 HNSW 索引，避免 cosine_distance 全表扫描（幂等）。
        await connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_chunk_embedding_hnsw "
                "ON td_knowledge_chunk USING hnsw (embedding vector_cosine_ops)"
            )
        )
        # 混合检索关键词通道：pg_trgm 扩展 + content_text 的 GIN trigram 索引，
        # 加速 ilike / similarity 模糊匹配（中文 n-gram，无第三方分词依赖）。
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_chunk_content_trgm "
                "ON td_knowledge_chunk USING gin (content_text gin_trgm_ops)"
            )
        )
        # 全文检索（fulltext 策略）：search_text 列（jieba 分词后空格分隔）+ tsvector 表达式索引。
        await connection.execute(
            text(
                "ALTER TABLE td_knowledge_chunk "
                "ADD COLUMN IF NOT EXISTS search_text TEXT"
            )
        )
        await connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_knowledge_chunk_search_tsv "
                "ON td_knowledge_chunk USING gin (to_tsvector('simple', search_text))"
            )
        )


async def session_dependency() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
