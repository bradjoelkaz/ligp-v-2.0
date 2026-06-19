"""Celery tasks for distributed content generation (Phase 17).

The heavy lifting (LLM generation, quality gate, DB status transitions) already
lives in :func:`api.routes.content._process_content`, which is an async,
never-raises worker that drives ``pending -> processing -> completed/failed``.
The Celery task is a thin, synchronous wrapper that runs it.

Why ``asyncio.run`` is safe here: a Celery worker process is *not* running an
event loop (unlike a FastAPI request handler), so creating one per task with
``asyncio.run`` is correct and avoids the "event loop already running" trap.

``_process_content`` swallows its own exceptions and records ``status='failed'``
with an error payload, so the worker never crashes on a single bad job.
"""

import asyncio
from typing import Any

from orchestration.celery_app import app
from utils.logger import get_logger

_log = get_logger(__name__)


@app.task(name="orchestration.tasks.generate_content_task", bind=True)
def generate_content_task(self, content_id: str, req_data: dict[str, Any]) -> str:
    """Generate content for ``content_id`` from a serialized request dict.

    Args:
        content_id: pre-persisted ('pending') content row id to drive.
        req_data: JSON-safe generation request
            (``node_id``, ``name``, ``platform``, ``tags``).

    Returns:
        The ``content_id`` (handy as the Celery result / for chaining).
    """
    node_id = str(req_data.get("node_id", ""))
    name = str(req_data.get("name", "") or "")
    platform = str(req_data.get("platform", "blog") or "blog")
    tags = list(req_data.get("tags", []) or [])

    _log.info(
        "celery_generate_start",
        extra={"content_id": content_id, "platform": platform},
    )

    # Reuse the existing async worker (handles status transitions + failures).
    from api.routes.content import _process_content

    asyncio.run(_process_content(content_id, node_id, name, platform, tags))

    _log.info("celery_generate_done", extra={"content_id": content_id})
    return content_id
