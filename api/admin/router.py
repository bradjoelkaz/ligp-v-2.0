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

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from api.admin import data

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

router = APIRouter(prefix="/admin", tags=["admin"])

_templates: Any = None


def get_templates() -> Any:
    """Lazily build and cache the Jinja2 templates environment."""
    global _templates
    if _templates is None:
        from fastapi.templating import Jinja2Templates

        _templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    return _templates


def _render(request: Request, name: str, **context: Any) -> HTMLResponse:
    base = {"request": request, "active": name.replace(".html", "")}
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
    return JSONResponse(data.graph_stats())
