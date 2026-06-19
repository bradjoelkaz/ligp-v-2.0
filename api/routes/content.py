"""Content API routes (Layer 14).

Built with a factory so importing this module does not require FastAPI; the
router is constructed lazily in :func:`get_router`.

NOTE: this module intentionally does NOT use ``from __future__ import
annotations``. The request body model (``GenerateRequest``) is defined locally
inside ``get_router``; under stringized annotations FastAPI/Pydantic cannot
resolve the ``ForwardRef`` to that local class when building the OpenAPI schema
(``/openapi.json``), so we keep annotations evaluated eagerly here.
"""

from typing import Any

from utils.logger import get_logger

_log = get_logger(__name__)


def _persist_content(content: dict[str, Any], platform: str) -> str | None:
    """Persist generated content to the DB when configured. Never raises.

    Returns the new content_id, or None when no DATABASE_URL is set or on any
    DB error (so content generation never fails because of persistence).
    """
    import os

    url = os.getenv("DATABASE_URL")
    if not url:
        return None
    try:
        from database.db_adapter import DBAdapter
        from database.repositories.content_repo import ContentRepository

        repo = ContentRepository(DBAdapter(url))
        try:
            return repo.save(
                {**content, "platform": platform, "status": content.get("status", "draft")}
            )
        finally:
            repo.db.close()
    except Exception:  # noqa: BLE001 - persistence must not break generation
        _log.warning("content_persist_failed")
        return None


def _list_history(limit: int = 50, status: str | None = None, since: str | None = None):
    """Read content history from the DB (empty list when no DB / on error)."""
    import os

    url = os.getenv("DATABASE_URL")
    if not url:
        return []
    try:
        from database.db_adapter import DBAdapter
        from database.repositories.content_repo import ContentRepository

        repo = ContentRepository(DBAdapter(url))
        try:
            return repo.list_content(limit=limit, status=status, since=since)
        finally:
            repo.db.close()
    except Exception:  # noqa: BLE001
        return []


def get_router():  # pragma: no cover - requires fastapi
    """Build and return the content APIRouter (lazy FastAPI import)."""
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel

    from content_factory.generators.blog_generator import BlogGenerator
    from content_factory.quality_gate import QualityGate

    router = APIRouter(prefix="/content", tags=["content"])

    class GenerateRequest(BaseModel):
        node_id: str
        name: str = ""
        platform: str = "blog"
        tags: list[str] = []

    @router.post("/generate")
    def generate(req: GenerateRequest) -> dict[str, Any]:
        from api.metrics import record_content_generated

        content = BlogGenerator().generate(
            {"id": req.node_id, "name": req.name or req.node_id, "tags": req.tags}, req.platform
        )
        passed, issues = QualityGate().check(content, req.platform)
        content["quality_passed"] = passed
        content["quality_issues"] = issues
        record_content_generated(req.platform, passed)
        # Persist (fire-and-forget) so it appears in /content/history.
        content_id = _persist_content(content, req.platform)
        if content_id:
            content["content_id"] = content_id
        return content

    # NOTE: declared before "/{content_id}" so it is not captured as a path param.
    @router.get("/history")
    def history(
        limit: int = 50, status: str | None = None, since: str | None = None
    ) -> list[dict[str, Any]]:
        return _list_history(limit=limit, status=status, since=since)

    @router.get("/{content_id}")
    def get_content(content_id: str) -> dict[str, Any]:
        raise HTTPException(status_code=404, detail="content store not wired in this build")

    return router
