"""Content API routes (Layer 14).

Built with a factory so importing this module does not require FastAPI; the
router is constructed lazily in :func:`get_router`.

NOTE: this module intentionally does NOT use ``from __future__ import
annotations``. The request body model (``GenerateRequest``) is defined locally
inside ``get_router``; under stringized annotations FastAPI/Pydantic cannot
resolve the ``ForwardRef`` to that local class when building the OpenAPI schema
(``/openapi.json``), so we keep annotations evaluated eagerly here.

Async queue (Phase 11 + Phase 17): ``POST /content/generate`` enqueues
generation and returns ``{content_id, status: "pending", queue}`` immediately;
``GET /content/status/{content_id}`` reports progress. When a Celery broker is
configured (``CELERY_BROKER_URL``) the job is published to the durable
Redis-backed Celery queue (``queue="celery"``); otherwise it falls back to an
in-process FastAPI BackgroundTask (``queue="background"``). Pass ``?sync=true``
for the legacy blocking behaviour. All DB access is fire-and-forget (no-op
without ``DATABASE_URL``; never raises into the worker).
"""

import json
import os
import uuid
from typing import Any

from utils.logger import get_logger

_log = get_logger(__name__)


def _repo():
    """Build a ContentRepository, or None when no DB is configured / on error."""
    url = os.getenv("DATABASE_URL")
    if not url:
        return None
    try:
        from database.db_adapter import DBAdapter
        from database.repositories.content_repo import ContentRepository

        return ContentRepository(DBAdapter(url))
    except Exception:  # noqa: BLE001
        return None


def _persist_pending(content_id: str, title: str, platform: str) -> None:
    """Insert a pending row (fire-and-forget)."""
    repo = _repo()
    if repo is None:
        return
    try:
        repo.save(
            {
                "content_id": content_id,
                "title": title,
                "body": "",
                "platform": platform,
                "status": "pending",
            }
        )
    except Exception:  # noqa: BLE001
        _log.warning("content_persist_pending_failed", extra={"content_id": content_id})
    finally:
        repo.db.close()


def _update_status(
    content_id: str, status: str, result: str | None = None, error: str | None = None
) -> None:
    """Update a content row's status/payload (fire-and-forget)."""
    repo = _repo()
    if repo is None:
        return
    try:
        repo.update_status(content_id, status, result=result, error=error)
    except Exception:  # noqa: BLE001
        _log.warning("content_update_status_failed", extra={"content_id": content_id})
    finally:
        repo.db.close()


async def _process_content(
    content_id: str, node_id: str, name: str, platform: str, tags: list[str]
) -> None:
    """Background worker: generate content and record the outcome in the DB.

    Never raises — failures are recorded as ``status='failed'`` so the user can
    observe them via ``GET /content/status/{id}``.
    """
    try:
        _update_status(content_id, "processing")
        from content_factory.generators.blog_generator import BlogGenerator
        from content_factory.quality_gate import QualityGate

        node = {"id": node_id, "name": name or node_id, "tags": tags}
        content = await BlogGenerator().generate_async(node, platform)
        passed, issues = QualityGate().check(content, platform)
        content["quality_passed"] = passed
        content["quality_issues"] = issues
        _update_status(content_id, "completed", result=json.dumps(content, default=str))
        from api.metrics import record_content_generated

        record_content_generated(platform, passed)
    except Exception as exc:  # noqa: BLE001 - background task must never crash
        _log.warning("content_process_failed", extra={"content_id": content_id, "error": str(exc)})
        _update_status(content_id, "failed", error=json.dumps({"error": str(exc)}))


async def _generate_blocking(
    node_id: str, name: str, platform: str, tags: list[str]
) -> dict[str, Any]:
    """Blocking generation used by ?sync=true (awaits generate_async directly).

    Must NOT call the synchronous ``BlogGenerator.generate`` (which uses
    ``asyncio.run``) because the endpoint runs inside the request event loop.
    """
    from api.metrics import record_content_generated
    from content_factory.generators.blog_generator import BlogGenerator
    from content_factory.quality_gate import QualityGate

    node = {"id": node_id, "name": name or node_id, "tags": tags}
    content = await BlogGenerator().generate_async(node, platform)
    passed, issues = QualityGate().check(content, platform)
    content["quality_passed"] = passed
    content["quality_issues"] = issues
    record_content_generated(platform, passed)
    content_id = str(uuid.uuid4())
    _persist_pending(content_id, content.get("title", ""), platform)
    _update_status(content_id, "completed", result=json.dumps(content, default=str))
    content["content_id"] = content_id
    return content


def _enqueue_celery(content_id: str, req_data: dict[str, Any]) -> bool:
    """Publish a generation job to the Celery queue.

    Returns ``True`` if the job was enqueued (Celery available and a broker is
    configured via ``CELERY_BROKER_URL``, or eager mode is on for tests), else
    ``False`` so the caller can fall back to in-process BackgroundTasks. Never
    raises — a broker/connection problem must not break the request.
    """
    if not os.getenv("CELERY_BROKER_URL") and not os.getenv("CELERY_TASK_ALWAYS_EAGER"):
        return False
    try:
        from orchestration.tasks import generate_content_task

        generate_content_task.delay(content_id, req_data)
        return True
    except Exception:  # noqa: BLE001 - fall back to BackgroundTasks on any failure
        _log.warning("celery_enqueue_failed_fallback", extra={"content_id": content_id})
        return False


def _list_history(limit: int = 50, status: str | None = None, since: str | None = None):
    """Read content history from the DB (empty list when no DB / on error)."""
    repo = _repo()
    if repo is None:
        return []
    try:
        return repo.list_content(limit=limit, status=status, since=since)
    except Exception:  # noqa: BLE001
        return []
    finally:
        repo.db.close()


def get_router():  # pragma: no cover - requires fastapi
    """Build and return the content APIRouter (lazy FastAPI import)."""
    from fastapi import APIRouter, BackgroundTasks, HTTPException
    from pydantic import BaseModel

    router = APIRouter(prefix="/content", tags=["content"])

    class GenerateRequest(BaseModel):
        node_id: str
        name: str = ""
        platform: str = "blog"
        tags: list[str] = []

    @router.post("/generate")
    async def generate(
        req: GenerateRequest, background_tasks: BackgroundTasks, sync: bool = False
    ) -> dict[str, Any]:
        if sync:
            return await _generate_blocking(req.node_id, req.name, req.platform, req.tags)
        content_id = str(uuid.uuid4())
        _persist_pending(content_id, f"[pending] {req.name or req.node_id}", req.platform)
        # Prefer the durable Celery/Redis queue; fall back to in-process
        # BackgroundTasks when no broker is configured (local/dev/offline).
        req_data = req.model_dump() if hasattr(req, "model_dump") else req.dict()
        queued = "celery" if _enqueue_celery(content_id, req_data) else "background"
        if queued == "background":
            background_tasks.add_task(
                _process_content, content_id, req.node_id, req.name, req.platform, req.tags
            )
        return {"content_id": content_id, "status": "pending", "queue": queued}

    @router.get("/history")
    async def history(
        limit: int = 50, status: str | None = None, since: str | None = None
    ) -> list[dict[str, Any]]:
        return _list_history(limit=limit, status=status, since=since)

    # Declared before "/{content_id}" so "status" is not captured as a path param.
    @router.get("/status/{content_id}")
    async def content_status(content_id: str) -> dict[str, Any]:
        repo = _repo()
        if repo is None:
            raise HTTPException(status_code=503, detail="content persistence requires DATABASE_URL")
        try:
            item = repo.get(content_id)
        finally:
            repo.db.close()
        if item is None:
            raise HTTPException(status_code=404, detail="content not found")
        payload = item.get("payload")
        return {
            "content_id": content_id,
            "status": item.get("status", "unknown"),
            "result": json.loads(payload) if payload else None,
        }

    @router.get("/{content_id}")
    async def get_content(content_id: str) -> dict[str, Any]:
        raise HTTPException(status_code=404, detail="content store not wired in this build")

    return router
