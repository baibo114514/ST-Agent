"""为存量 KnowledgeChunk 回填 search_text（jieba 分词后的全文检索列）。

引入 fulltext 检索策略后，已有 chunk 的 search_text 列为空，需用 jieba 对其
content_text 分词后回填。幂等：已有 search_text 的 chunk 跳过。
"""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from services.knowledge_service.db import AsyncSessionLocal
from services.knowledge_service.metadata import tokenize_for_search
from services.knowledge_service.models import KnowledgeChunk


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill search_text for existing knowledge chunks.")
    parser.add_argument("--kb-id", action="append", default=[], help="Only migrate this KB; may be repeated.")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without committing them.")
    return parser.parse_args()


async def backfill(kb_ids: list[str], dry_run: bool) -> tuple[int, int]:
    filled = 0
    skipped = 0
    async with AsyncSessionLocal() as session:
        statement = select(KnowledgeChunk).where(KnowledgeChunk.search_text.is_(None))
        if kb_ids:
            statement = statement.where(KnowledgeChunk.kb_id.in_(kb_ids))
        rows = (await session.execute(statement)).scalars().all()
        for chunk in rows:
            if not chunk.content_text:
                skipped += 1
                continue
            chunk.search_text = tokenize_for_search(chunk.content_text)
            filled += 1
        if not dry_run:
            await session.commit()
    return filled, skipped


def main() -> None:
    args = parse_args()
    filled, skipped = asyncio.run(backfill(args.kb_id, args.dry_run))
    mode = "dry-run" if args.dry_run else "committed"
    print(f"search_text backfill {mode}: filled={filled}, skipped={skipped}")


if __name__ == "__main__":
    main()
