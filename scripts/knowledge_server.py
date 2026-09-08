"""
Local knowledge-service development server.

This wrapper keeps Windows on the asyncio selector loop and starts the
independent knowledge microservice on port 8010.
"""

import asyncio
import os
import sys

os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("KNOWLEDGE_SERVICE_RELOAD", "false")

import uvicorn

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

os.environ.setdefault("APP_ENV", "development")


if __name__ == "__main__":
    uvicorn.run(
        "services.knowledge_service.main:app",
        host="127.0.0.1",
        port=int(os.getenv("KNOWLEDGE_SERVICE_PORT", "8010")),
        reload=os.getenv("KNOWLEDGE_SERVICE_RELOAD", "false").lower() in ("true", "1", "yes"),
        loop="asyncio",
    )
