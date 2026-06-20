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
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from api.admin import data
from api.metrics import metrics_snapshot, record_graph_size
from utils.logger import get_logger

_log = get_logger(__name__)

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


@router.get("/trends", response_class=HTMLResponse, summary="Real-time Trends")
async def trends_page(request: Request) -> HTMLResponse:
    """Render the real-time news & hot issues trends board."""
    return _render(request, "trends.html")


@router.get("/os", response_class=HTMLResponse, summary="OS management dashboard")
async def os_page(request: Request) -> HTMLResponse:
    """Render the 1-person AI holding-company management console."""
    return _render(request, "os.html", os=data.os_dashboard())


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


# -- real-time trends (collect -> Gemini analysis, cached in-process) --------

# 15-minute in-process cache to avoid hammering the feeds + LLM APIs on every
# dashboard load. ``force_refresh=true`` bypasses the TTL.
_cached_trends: dict[str, Any] = {}
_last_trend_update: float = 0.0
CACHE_TTL_SECONDS = 900.0  # 15 minutes


@router.get("/api/trends", summary="Retrieve real-time clustered trends using Gemini")
async def api_trends(force_refresh: bool = False) -> JSONResponse:
    """Collect from Reddit/Naver/Google, run Gemini analysis, persist, and return topics.

    Serves the in-process cache while it is fresh. On a refresh (cache expired or
    ``force_refresh=true``) it crawls + analyzes, persists raw articles and topics
    to the local SQLite asset store, and updates the cache. If crawling/LLM fails,
    it degrades gracefully to the latest topics previously saved in SQLite so the
    dashboard keeps working offline and across restarts.
    """
    global _cached_trends, _last_trend_update
    now = time.time()

    # Trends asset store (local SQLite); imported lazily to keep import-time light.
    from database.db_store import (
        get_latest_trends,
        init_db,
        save_raw_articles,
        save_trend_topics,
    )

    init_db()

    # Serve a fresh in-process cache without touching the network/LLM.
    if not force_refresh and _cached_trends and (now - _last_trend_update) < CACHE_TTL_SECONDS:
        return JSONResponse(_cached_trends)

    try:
        from ingestion.collectors import collect_all_feeds
        from nlp.llm_processor import GeminiProcessor

        # 1. Collect live articles and persist the raw documents.
        articles = collect_all_feeds()
        save_raw_articles(articles)

        # 2. Cluster into topics (+ Suno / Nano Banana prompts).
        processor = GeminiProcessor()
        trends_result = processor.analyze_trends(articles)
        topics = trends_result.get("topics", [])

        # 3. Persist analyzed topics to SQLite (asset accumulation).
        save_trend_topics(topics)

        # 3b. Record an estimated LLM spend (only when a real key is configured,
        #     i.e. not the mock fallback) so the OS dashboard ROI reflects cost.
        if os.getenv("OPENROUTER_API_KEY") or os.getenv("GEMINI_API_KEY"):
            try:
                from database.db_store import record_cost

                record_cost("llm:analyze_trends", 0.002)
            except Exception:  # noqa: BLE001 - cost ledger is best-effort
                pass

        # 4. Record a Layer-4 volume snapshot for the tracked graph terms so
        #    velocity/acceleration can be computed from real history over time.
        try:
            from time_engine.volume_tracker import record_snapshot

            terms = [n.get("name", "") for n in data.graph_records().get("nodes", [])]
            record_snapshot(articles, terms)
        except Exception as snap_exc:  # noqa: BLE001 - snapshot is best-effort
            _log.warning("trend_volume_snapshot_failed", extra={"error": str(snap_exc)})

        _cached_trends = {
            "topics": topics,
            "collected_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
            "raw_count": len(articles),
        }
        _last_trend_update = now
    except Exception as exc:  # noqa: BLE001 - degrade to persisted history
        db_topics = get_latest_trends(limit=10)
        _cached_trends = {
            "error": f"Failed to crawl online: {str(exc)}. Loaded historical DB topics.",
            "topics": db_topics,
            "collected_at": "Offline DB",
            "raw_count": len(db_topics),
        }

    return JSONResponse(_cached_trends)


@router.get("/api/obsidian-export", summary="Export the knowledge graph to an Obsidian vault")
async def api_obsidian_export() -> JSONResponse:
    """Render the current graph (DB-or-seed) as Obsidian Markdown notes.

    Writes one ``.md`` note per node (edges become ``[[wikilinks]]``) plus an
    index into ``data/obsidian_vault/`` and returns a summary. Degrades to an
    error payload rather than raising so the dashboard stays responsive.
    """
    try:
        from graph.obsidian_bridge import export_to_vault

        repo_root = Path(__file__).resolve().parents[2]
        vault_dir = str(repo_root / "data" / "obsidian_vault")
        summary = export_to_vault(data.graph_records(), vault_dir)
        return JSONResponse(summary)
    except Exception as exc:  # noqa: BLE001 - never 500 the admin API
        return JSONResponse({"error": f"Obsidian export failed: {str(exc)}"}, status_code=500)


@router.get("/api/trend-velocity", summary="Computed velocity/acceleration per tracked term")
async def api_trend_velocity() -> JSONResponse:
    """Compute real Layer-4 trend metrics from the persisted volume time-series.

    Reads the accumulated ``term_volume`` history for each knowledge-graph term
    and runs :class:`TrendDetector` to produce velocity, acceleration and trend
    state. Read-only: history is accrued by ``/api/trends`` refreshes.
    """
    try:
        from database.db_store import init_db
        from time_engine.volume_tracker import analyze_tracked

        init_db()
        terms = [n.get("name", "") for n in data.graph_records().get("nodes", [])]
        tracked = analyze_tracked(terms)
        return JSONResponse({"tracked": tracked, "terms": len(terms), "count": len(tracked)})
    except Exception as exc:  # noqa: BLE001 - never 500 the admin API
        return JSONResponse({"error": f"Trend velocity failed: {str(exc)}"}, status_code=500)


@router.get("/api/os-metrics", summary="OS dashboard metrics (mission/finance/portfolio)")
async def api_os_metrics() -> JSONResponse:
    """Return the management-console metrics as JSON."""
    return JSONResponse(data.os_dashboard())


class FeedbackIn(BaseModel):
    """Performance feedback for one published content item (L7 input)."""

    content_id: str
    platform: str = "unknown"
    expected_score: float = 0.0
    features: dict[str, float] | None = None
    views: int = 0
    clicks: int = 0
    subscribers: int = 0
    revenue: float = 0.0


@router.post("/api/feedback", summary="Record content performance feedback (L7)")
async def api_record_feedback(
    payload: FeedbackIn, _: None = Depends(verify_admin_key)
) -> JSONResponse:
    """Persist a performance-feedback record for the calibration loop."""
    try:
        from feedback_engine.feedback_loop import record_performance

        metrics = {
            "views": payload.views,
            "clicks": payload.clicks,
            "subscribers": payload.subscribers,
            "revenue": payload.revenue,
        }
        actual = record_performance(
            payload.content_id,
            payload.platform,
            payload.expected_score,
            metrics,
            features=payload.features,
        )
        return JSONResponse({"recorded": True, "actual_score": actual})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": f"Feedback record failed: {str(exc)}"}, status_code=500)


@router.post("/api/calibrate", summary="Run L7 weight self-calibration")
async def api_calibrate(_: None = Depends(verify_admin_key)) -> JSONResponse:
    """Run one calibration pass and persist updated opportunity-score weights."""
    try:
        from database.db_store import init_db
        from feedback_engine.feedback_loop import calibrate

        init_db()
        return JSONResponse(calibrate())
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": f"Calibration failed: {str(exc)}"}, status_code=500)


class DeployRequest(BaseModel):
    """Deploy a stored content asset to a (virtual) social platform."""

    content_id: str
    platform: str = "tistory"


@router.post("/api/deploy", summary="Virtually deploy a content asset to a platform")
async def api_deploy(payload: DeployRequest, _: None = Depends(verify_admin_key)) -> JSONResponse:
    """Deploy a stored content asset; real publisher when keyed, else mock."""
    try:
        from database.db_store import get_generated_content, init_db
        from publisher.deploy_engine import deploy

        init_db()
        content = get_generated_content(payload.content_id) or {"content_id": payload.content_id}
        return JSONResponse(deploy(content, payload.platform))
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": f"Deploy failed: {str(exc)}"}, status_code=500)


class PerformanceRequest(BaseModel):
    """Collect (or simulate) performance for a deployed item and calibrate L7."""

    content_id: str
    platform: str = "unknown"
    expected_score: float = 0.0
    features: dict[str, float] | None = None
    calibrate: bool = True


@router.post("/api/collect-performance", summary="Collect performance + run L7 calibration")
async def api_collect_performance(
    payload: PerformanceRequest, _: None = Depends(verify_admin_key)
) -> JSONResponse:
    """Simulate/collect market performance, persist as feedback, and calibrate."""
    try:
        from database.db_store import init_db
        from feedback_engine.performance_collector import collect_and_calibrate, collect_performance

        init_db()
        item = {
            "content_id": payload.content_id,
            "platform": payload.platform,
            "expected_score": payload.expected_score,
            "features": payload.features,
        }
        if payload.calibrate:
            summary = collect_and_calibrate([item])
            return JSONResponse({"collected": 1, "calibration": summary})
        result = collect_performance(
            payload.content_id, payload.platform, payload.expected_score, features=payload.features
        )
        return JSONResponse({"collected": 1, **result})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": f"Collect performance failed: {str(exc)}"}, status_code=500)


class ScriptRequest(BaseModel):
    """Request to generate a 2-column YouTube script from a topic/node."""

    title: str
    summary: str = ""
    platform: str = "youtube_long"  # youtube_long | youtube_shorts
    entities: list[dict[str, str]] | None = None


@router.post("/api/generate-script", summary="Generate + persist a 2-column YouTube script")
async def api_generate_script(
    payload: ScriptRequest, _: None = Depends(verify_admin_key)
) -> JSONResponse:
    """Generate a 2-column YouTube video script and store it (INSERT OR REPLACE)."""
    try:
        from content_factory.generators.youtube_script_generator import YouTubeScriptGenerator
        from database.db_store import init_db, save_generated_content

        init_db()
        node = {
            "title": payload.title,
            "summary": payload.summary,
            "entities": payload.entities or [],
        }
        content = YouTubeScriptGenerator().generate(node, platform=payload.platform)
        content_id = save_generated_content(content)
        content["content_id"] = content_id
        return JSONResponse(content)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": f"Script generation failed: {str(exc)}"}, status_code=500)


@router.get("/api/content", summary="List recent generated content assets")
async def api_list_content() -> JSONResponse:
    """Return metadata for recently generated content assets."""
    try:
        from database.db_store import init_db, list_generated_content

        init_db()
        return JSONResponse({"items": list_generated_content()})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": f"List content failed: {str(exc)}"}, status_code=500)


@router.get("/api/content/{content_id}", summary="Fetch one generated content asset")
async def api_get_content(content_id: str) -> JSONResponse:
    """Return a single generated content asset (e.g. a YouTube script) by id."""
    try:
        from database.db_store import get_generated_content, init_db

        init_db()
        content = get_generated_content(content_id)
        if content is None:
            return JSONResponse({"error": "not found"}, status_code=404)
        return JSONResponse(content)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"error": f"Get content failed: {str(exc)}"}, status_code=500)


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
