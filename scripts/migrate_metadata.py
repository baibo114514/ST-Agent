"""Migrate existing knowledge-document metadata to the canonical JSON shape."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from services.knowledge_service.db import AsyncSessionLocal
from services.knowledge_service.extractors import extract_markdown_front_matter
from services.knowledge_service.metadata import normalize_metadata
from services.knowledge_service.models import KnowledgeBase, KnowledgeDocument


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate knowledge document metadata JSON.")
    parser.add_argument("--kb-id", action="append", default=[], help="Only migrate this KB; may be repeated.")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without committing them.")
    return parser.parse_args()


def extracted_document_metadata(document: KnowledgeDocument) -> dict[str, Any]:
    content = document.content_text or ""
    if document.file_name and document.file_name.lower().endswith((".md", ".markdown")):
        return extract_markdown_front_matter(content).get("metadata") or {}
    return {}


async def migrate(kb_ids: list[str], dry_run: bool) -> tuple[int, int]:
    migrated = 0
    skipped = 0
    migrated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    async with AsyncSessionLocal() as session:
        statement = select(KnowledgeDocument, KnowledgeBase).join(
            KnowledgeBase, KnowledgeBase.id == KnowledgeDocument.kb_id
        )
        if kb_ids:
            statement = statement.where(KnowledgeDocument.kb_id.in_(kb_ids))
        rows = (await session.execute(statement)).all()
        for document, knowledge_base in rows:
            current = document.metadata_json or {}
            extracted = extracted_document_metadata(document)
            normalized = normalize_metadata(
                current,
                extracted_metadata=extracted,
                file_name=document.file_name,
                ingest_fields={
                    "blobSha256": current.get("blobSha256"),
                    "source": current.get("source") or "migration",
                    "metadataSource": "markdown_metadata_block" if extracted else "existing_metadata",
                    "migratedAt": migrated_at,
                },
            )
            if normalized == current:
                skipped += 1
                continue
            document.metadata_json = normalized
            migrated += 1
        if not dry_run:
            await session.commit()
    return migrated, skipped


def main() -> None:
    args = parse_args()
    migrated, skipped = asyncio.run(migrate(args.kb_id, args.dry_run))
    mode = "dry-run" if args.dry_run else "committed"
    print(f"Metadata migration {mode}: migrated={migrated}, skipped={skipped}")


if __name__ == "__main__":
    main()
