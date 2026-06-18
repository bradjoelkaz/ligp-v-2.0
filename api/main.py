"""FastAPI application entrypoint (Layer 14).

``create_app`` builds the app lazily so importing this module does not require
FastAPI to be installed (keeps unit-test collection import-safe).
"""

from __future__ import annotations

from typing import Any

from utils.logger import get_logger

_log = get_logger(__name__)


def create_app() -> Any:  # pragma: no cover - requires fastapi
    """Construct the FastAPI app with all routers and a health check."""
    from fastapi import FastAPI

    from api.routes import content, experiments_routes, graph_routes

    app = FastAPI(title="IIGP v2.0 API", version="2.0.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "iigp", "version": "2.0.0"}

    app.include_router(content.get_router())
    app.include_router(graph_routes.get_router())
    app.include_router(experiments_routes.get_router())
    return app
