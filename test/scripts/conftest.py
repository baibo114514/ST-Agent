from __future__ import annotations

import asyncio
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def run_async(awaitable):
    """Run one coroutine without requiring pytest-asyncio."""
    return asyncio.run(awaitable)

