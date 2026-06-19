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
        return content

    @router.get("/{content_id}")
    def get_content(content_id: str) -> dict[str, Any]:
        raise HTTPException(status_code=404, detail="content store not wired in this build")

    return router
