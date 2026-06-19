"""IIGP v2.0 API application factory (Phase 8 + Phase 1-7 integration).

Exposes ``create_app()`` — a factory that builds the FastAPI application,
installs CORS and the Prometheus ASGI middleware, mounts ``/metrics`` and
includes every router:

* Phase 8 : ``api.routes.health`` (health/ready/version), ``api.admin.router``
            (admin dashboard), plus ``/`` and ``/metrics``.
* Phase 1-7 : ``api.routes.content``, ``api.routes.graph_routes`` and
              ``api.routes.experiments_routes`` (built via their ``get_router``
              factories).

FastAPI is imported lazily *inside* the factory so this module stays importable
in dependency-light environments (e.g. offline CI bootstrap / unit-test
collection). Run with::

    uvicorn api.main:create_app --factory --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from api.metrics import PrometheusMiddleware, render_latest, setup_metrics
from utils.logger import get_logger

if TYPE_CHECKING:  # pragma: no cover - typing only
    from fastapi import FastAPI

_log = get_logger("iigp.api")


def _cors_origins() -> list[str]:
    """Resolve allowed CORS origins from settings, defaulting to ``["*"]``."""
    try:
        from utils.config_loader import load_config

        api_cfg = load_config("settings").get("api", {})
        origins = api_cfg.get("cors_origins")
        if isinstance(origins, list) and origins:
            return [str(o) for o in origins]
    except Exception:  # noqa: BLE001 - never fail app construction on config issues
        pass
    return ["*"]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: initialise observability on startup, clean up on exit."""
    setup_metrics()
    _log.info("IIGP API starting up (metrics initialised)")
    try:
        yield
    finally:
        _log.info("IIGP API shutting down")


def create_app(**fastapi_kwargs: Any) -> FastAPI:
    """Build and configure the FastAPI application instance."""
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import Response

    from api.admin.router import router as admin_router
    from api.routes import content, experiments_routes, graph_routes
    from api.routes.health import router as health_router

    app = FastAPI(
        title="IIGP v2.0 API",
        version="2.0.0",
        description="Graph-centric, probability-driven content revenue engine.",
        lifespan=lifespan,
        **fastapi_kwargs,
    )

    # CORS (Phase 5/7): configurable origins, permissive default for local/dev.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API key authentication (Phase 9): enforced only when API_SECRET_KEY is set;
    # public routes (health/metrics/admin/docs) always bypass.
    from api.middleware.auth import APIKeyMiddleware

    app.add_middleware(APIKeyMiddleware)

    # Observability middleware (records count/latency/concurrency).
    app.add_middleware(PrometheusMiddleware)

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        body, content_type = render_latest()
        return Response(content=body, media_type=content_type)

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {"service": "iigp", "version": "2.0.0", "admin": "/admin/", "docs": "/docs"}

    # Phase 8 routers.
    app.include_router(health_router)
    app.include_router(admin_router)

    # Phase 1-7 API routers (built lazily via their factories).
    app.include_router(content.get_router())
    app.include_router(graph_routes.get_router())
    app.include_router(experiments_routes.get_router())

    return app
