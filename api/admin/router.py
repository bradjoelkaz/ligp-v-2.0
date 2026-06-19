"""Admin dashboard router (Phase 8).

Module-level ``router`` (an ``APIRouter``) so ``api.main`` can ``include_router``.
HTML pages are rendered with Jinja2 (dark theme + D3.js force graph); JSON data
endpoints back the client-side fetches. The Jinja2 environment is created lazily
so importing this module only requires FastAPI, not Jinja2 directly.

Live data sources (graph_store, scoring_engine, experiments) are wired in during
Phases 1-7; for now the views are backed by :mod:`api.admin.data`, which reads
the cold-start seed graph and validated config.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from api.admin import data
from api.metrics import metrics_snapshot, record_graph_size

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

router = APIRouter(prefix="/admin", tags=["admin"])

_templates: Any = None


# Module-level request models (defined at module scope so their forward
# references resolve during OpenAPI schema generation).
class NodeIn(BaseModel):
    node_id: str
    type: str = "topic"
    name: str = ""
    weight: float = 1.0


class EdgeIn(BaseModel):
    from_node: str
    to_node: str
    relation_type: str = "related_to"
    weight: float = 0.5


async def verify_admin_key(x_api_key: str = Header(..., alias="X-API-Key")) -> None:
    """Authorise graph-mutation requests via the ``X-API-Key`` header.

    Read-only GET endpoints stay public; only the POST (write) endpoints depend
    on this. The expected key comes from ``$ADMIN_API_KEY`` (read at request
    time). A missing header is rejected by FastAPI (422); an unset server key
    yields 503; a mismatch yields 401.
    """
    admin_key = os.getenv("ADMIN_API_KEY", "")
    if not admin_key:
        raise HTTPException(status_code=503, detail="admin API key not configured")
    if x_api_key != admin_key:
        raise HTTPException(status_code=401, detail="invalid API key")


def _graph_repo() -> Any:
    """Build a GraphRepository, or 503 when no database is configured."""
    url = os.getenv("DATABASE_URL")
    if not url:
        raise HTTPException(status_code=503, detail="graph persistence requires DATABASE_URL")
    from database.db_adapter import DBAdapter
    from database.repositories.graph_repo import GraphRepository

    return GraphRepository(DBAdapter(url))


def get_templates() -> Any:
    """Lazily build and cache the Jinja2 templates environment."""
    global _templates
    if _templates is None:
        from fastapi.templating import Jinja2Templates

        _templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    return _templates


def _render(request: Request, name: str, **context: Any) -> HTMLResponse:
    base = {"active": name.replace(".html", "")}
    base.update(context)
    return get_templates().TemplateResponse(request, name, base)


# -- HTML pages --------------------------------------------------------------


@router.get("/", response_class=HTMLResponse, summary="Dashboard home")
async def index(request: Request) -> HTMLResponse:
    return _render(
        request,
        "index.html",
        summary=data.dashboard_summary(),
        stats=data.graph_stats(),
        revenue_paths=data.top_revenue_paths(),
        live=metrics_snapshot(),
    )


@router.get("/graph", response_class=HTMLResponse, summary="Graph explorer")
async def graph_page(request: Request) -> HTMLResponse:
    return _render(request, "graph.html", stats=data.graph_stats())


@router.get("/content", response_class=HTMLResponse, summary="Content queue")
async def content_page(request: Request) -> HTMLResponse:
    return _render(request, "content.html", items=data.content_queue())


@router.get("/experiments", response_class=HTMLResponse, summary="A/B experiments")
async def experiments_page(request: Request) -> HTMLResponse:
    return _render(request, "experiments.html", experiments=data.experiment_summary())


@router.get("/settings", response_class=HTMLResponse, summary="Configuration view")
async def settings_page(request: Request) -> HTMLResponse:
    return _render(request, "settings.html", settings=data.settings_view())


# -- JSON data endpoints (consumed by the D3 force graph / tiles) ------------


@router.get("/api/graph", summary="Graph data (D3 nodes/links)")
async def api_graph() -> JSONResponse:
    return JSONResponse(data.graph_payload())


@router.get("/api/stats", summary="Graph summary stats")
async def api_stats() -> JSONResponse:
    stats = data.graph_stats()
    # Reflect the rendered graph size into the Prometheus gauges (in-process).
    record_graph_size(stats["node_count"], stats["edge_count"])
    return JSONResponse(stats)


@router.get("/api/content-stats", summary="Content generation stats")
async def api_content_stats() -> JSONResponse:
    return JSONResponse(data.content_stats())


# -- write endpoints (persist to graph_nodes / graph_edges) ------------------


@router.post(
    "/api/node",
    status_code=201,
    dependencies=[Depends(verify_admin_key)],
    summary="Create or update a graph node",
)
async def upsert_node(node: NodeIn) -> JSONResponse:
    repo = _graph_repo()
    try:
        node_id = repo.upsert_node(node.node_id, node.type, node.name, node.weight)
    finally:
        repo.db.close()
    return JSONResponse({"node_id": node_id}, status_code=201)


@router.post(
    "/api/edge",
    status_code=201,
    dependencies=[Depends(verify_admin_key)],
    summary="Create or update a graph edge",
)
async def upsert_edge(edge: EdgeIn) -> JSONResponse:
    repo = _graph_repo()
    try:
        edge_id = repo.upsert_edge(edge.from_node, edge.to_node, edge.relation_type, edge.weight)
    finally:
        repo.db.close()
    return JSONResponse({"edge_id": edge_id}, status_code=201)
