"""IIGP v2.0 API application factory (Phase 8).

Exposes ``create_app()`` — a factory that builds the FastAPI application,
installs the Prometheus ASGI middleware, mounts ``/metrics`` and includes the
module-level routers (``api.routes.health``, ``api.admin.router``).

FastAPI is imported lazily *inside* the factory so this module stays importable
in dependency-light environments (e.g. offline CI bootstrap). Run with::

    uvicorn api.main:create_app --factory --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from api.metrics import PrometheusMiddleware, render_latest, setup_metrics

if TYPE_CHECKING:  # pragma: no cover - typing only
    from fastapi import FastAPI

logger = logging.getLogger("iigp.api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: initialise observability on startup, clean up on exit."""
    setup_metrics()
    logger.info("IIGP API starting up (metrics initialised)")
    try:
        yield
    finally:
        logger.info("IIGP API shutting down")


def create_app(**fastapi_kwargs: Any) -> FastAPI:
    """Build and configure the FastAPI application instance."""
    from fastapi import FastAPI
    from fastapi.responses import Response

    from api.admin.router import router as admin_router
    from api.routes.health import router as health_router

    app = FastAPI(
        title="IIGP v2.0 API",
        version="2.0.0",
        description="Graph-centric, probability-driven content revenue engine.",
        lifespan=lifespan,
        **fastapi_kwargs,
    )

    # Observability middleware (records count/latency/concurrency).
    app.add_middleware(PrometheusMiddleware)

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        body, content_type = render_latest()
        return Response(content=body, media_type=content_type)

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {"service": "iigp", "version": "2.0.0", "admin": "/admin/", "docs": "/docs"}

    app.include_router(health_router)
    app.include_router(admin_router)

    return app
