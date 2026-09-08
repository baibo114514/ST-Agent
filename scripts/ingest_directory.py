"""
Bulk-ingest a local document directory into knowledge-service.

This is intended for hybrid local development where the knowledge-service is
running on the host and the source documents are also on the host filesystem.
"""

import argparse
import asyncio
import json
import mimetypes
import sys
from pathlib import Path
from typing import Iterable, List

import httpx
from sqlalchemy.pool import QueuePool
from sqlmodel import Session, select
from sqlmodel import create_engine

from app.core.config import settings as app_settings
from app.models.agent import PlatformAgent
from app.schemas.agent import AgentKnowledgeConfig
from services.knowledge_service.config import settings as knowledge_settings


SUPPORTED_SUFFIXES = {
    ".pdf",
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".json",
    ".html",
    ".htm",
    ".log",
}
RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


DATABASE_URL = (
    f"postgresql+psycopg://{app_settings.POSTGRES_USER}:{app_settings.POSTGRES_PASSWORD}"
    f"@{app_settings.POSTGRES_HOST}:{app_settings.POSTGRES_PORT}/{app_settings.POSTGRES_DB}"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest a document directory into knowledge-service.")
    parser.add_argument("--directory", required=True, help="Local directory that contains documents.")
    parser.add_argument("--kb-id", default="", help="Target knowledge-base id.")
    parser.add_argument("--agent-code", default="", help="Resolve target kb from a platform agent code.")
    parser.add_argument("--kb-index", type=int, default=0, help="When an agent binds multiple KBs, choose this index.")
    parser.add_argument("--offset", type=int, default=0, help="Skip this many matched files before ingesting.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum number of files to ingest. 0 means no limit.")
    parser.add_argument("--concurrency", type=int, default=2, help="Number of files to ingest concurrently.")
    parser.add_argument("--retries", type=int, default=3, help="Retries for transient upload failures.")
    parser.add_argument("--retry-delay", type=float, default=2.0, help="Base retry delay in seconds.")
    parser.add_argument("--timeout", type=float, default=600.0, help="Per-request timeout in seconds.")
    parser.add_argument("--skip-existing", action="store_true", help="Skip files whose sourceRef already exists.")
    parser.add_argument("--dry-run", action="store_true", help="Only print the files that would be ingested.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8010", help="Knowledge-service base URL.")
    return parser.parse_args()


def supported_files(directory: Path) -> List[Path]:
    files = [
        path
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    ]
    files.sort(key=lambda item: str(item.relative_to(directory)).lower())
    return files


def resolve_kb_id_sync(kb_id: str, agent_code: str, kb_index: int) -> str:
    if kb_id:
        return kb_id
    if not agent_code:
        raise ValueError("--kb-id or --agent-code is required")

    engine = create_engine(
        DATABASE_URL,
        pool_size=app_settings.POSTGRES_POOL_SIZE,
        max_overflow=app_settings.POSTGRES_MAX_OVERFLOW,
        poolclass=QueuePool,
    )
    with Session(engine) as session:
        agent = session.exec(
            select(PlatformAgent).where(PlatformAgent.agent_code == agent_code.strip().lower())
        ).first()
    if not agent:
        raise ValueError(f"platform agent not found: {agent_code}")

    knowledge = AgentKnowledgeConfig.model_validate((agent.config_json or {}).get("knowledge", {}))
    if not knowledge.enabled or not knowledge.kb_ids:
        raise ValueError(f"platform agent has no enabled knowledge base: {agent_code}")
    if kb_index < 0 or kb_index >= len(knowledge.kb_ids):
        raise ValueError(f"kb index out of range: {kb_index}")
    return knowledge.kb_ids[kb_index]


def print_plan(directory: Path, kb_id: str, files: Iterable[Path], limit: int) -> None:
    selected = list(files)
    if limit > 0:
        selected = selected[:limit]
    print(f"Target KB: {kb_id}")
    print(f"Source directory: {directory}")
    print(f"Matched files: {len(selected)}")
    for path in selected[:20]:
        print(f"- {path.relative_to(directory)}")
    if len(selected) > 20:
        print(f"... and {len(selected) - 20} more")


def is_retryable_upload_error(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_STATUS_CODES
    return isinstance(exc, (httpx.TimeoutException, httpx.NetworkError))


async def upload_one(
    client: httpx.AsyncClient,
    base_url: str,
    kb_id: str,
    directory: Path,
    path: Path,
    retries: int,
    retry_delay: float,
) -> str:
    relative_path = path.relative_to(directory).as_posix()
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    metadata = {
        "relativePath": relative_path,
        "source": "directory_upload",
    }
    body = await asyncio.to_thread(path.read_bytes)
    attempts = max(1, retries + 1)
    for attempt in range(1, attempts + 1):
        try:
            response = await client.post(
                f"{base_url.rstrip('/')}/internal/v1/kb/bases/{kb_id}/ingest/file",
                headers={"X-KB-Service-Token": knowledge_settings.service_token},
                data={
                    "title": path.stem,
                    "sourceRef": relative_path,
                    "metadata": json.dumps(metadata, ensure_ascii=False),
                },
                files={"file": (path.name, body, content_type)},
            )
            if response.status_code >= 400:
                raise httpx.HTTPStatusError(
                    f"{response.status_code} {response.text[:500]}",
                    request=response.request,
                    response=response,
                )
            payload = response.json()
            return str(payload.get("id") or payload.get("status") or "submitted")
        except Exception as exc:
            if attempt >= attempts or not is_retryable_upload_error(exc):
                raise
            await asyncio.sleep(max(0.1, retry_delay) * attempt)

    raise RuntimeError("upload retry loop exited unexpectedly")


async def existing_source_refs(client: httpx.AsyncClient, base_url: str, kb_id: str) -> set[str]:
    response = await client.get(
        f"{base_url.rstrip('/')}/internal/v1/kb/bases/{kb_id}/documents",
        headers={"X-KB-Service-Token": knowledge_settings.service_token},
        params={"includeArchived": "false"},
    )
    response.raise_for_status()
    payload = response.json()
    return {
        str(item.get("sourceRef"))
        for item in payload.get("items", [])
        if item.get("sourceRef")
    }


async def ingest_directory(args: argparse.Namespace) -> None:
    directory = Path(args.directory).expanduser().resolve()
    if not directory.is_dir():
        raise ValueError(f"directory does not exist: {directory}")
    kb_id = await asyncio.to_thread(resolve_kb_id_sync, args.kb_id, args.agent_code, args.kb_index)
    files = supported_files(directory)
    if args.offset > 0:
        files = files[args.offset :]
    if args.limit > 0:
        files = files[: args.limit]
    print_plan(directory, kb_id, files, args.limit)
    if args.dry_run:
        return
    if not files:
        return

    base_url = args.base_url
    concurrency = max(1, args.concurrency)
    headers_ready = bool(knowledge_settings.service_token)
    if not headers_ready:
        raise ValueError("KNOWLEDGE_SERVICE_TOKEN is required")

    completed = 0
    failed = 0
    semaphore = asyncio.Semaphore(concurrency)
    request_timeout = max(30.0, float(args.timeout))
    async with httpx.AsyncClient(timeout=httpx.Timeout(request_timeout, connect=5.0), trust_env=False) as client:
        if args.skip_existing:
            existing_refs = await existing_source_refs(client, base_url, kb_id)
            before_skip = len(files)
            files = [
                path
                for path in files
                if path.relative_to(directory).as_posix() not in existing_refs
            ]
            print(f"Skipped existing files: {before_skip - len(files)}")

        async def run_one(path: Path) -> tuple[str, Path, str, str]:
            async with semaphore:
                try:
                    job_id = await upload_one(
                        client,
                        base_url,
                        kb_id,
                        directory,
                        path,
                        retries=max(0, args.retries),
                        retry_delay=max(0.1, args.retry_delay),
                    )
                    return ("ok", path, job_id, "")
                except Exception as exc:
                    return ("failed", path, "", str(exc))

        tasks = [asyncio.create_task(run_one(path)) for path in files]
        for task in asyncio.as_completed(tasks):
            status_value, path, job_id, error_message = await task
            relative_path = path.relative_to(directory)
            if status_value == "ok":
                completed += 1
                print(f"[{completed + failed}/{len(files)}] ok {relative_path} job={job_id}")
            else:
                failed += 1
                print(f"[{completed + failed}/{len(files)}] failed {relative_path}: {error_message}")
    print(f"Finished. completed={completed}, failed={failed}")


def main() -> None:
    args = parse_args()
    asyncio.run(ingest_directory(args))


if __name__ == "__main__":
    main()
