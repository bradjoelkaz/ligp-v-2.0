"""Data access helpers for the admin dashboard.

These helpers are intentionally free of any web-framework dependency so they can
be unit-tested directly. During Phase 8 the live graph/scoring/experiment
backends (Phases 1-7) are not yet wired in, so the dashboard reads the
cold-start seed graph (``data/seed/*.json``) and the validated ``config/`` YAML
to render representative, non-empty views. Each function degrades gracefully if
an optional dependency (PyYAML) or data file is missing.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SEED_DIR = ROOT / "data" / "seed"

# Node type -> hex colour used by the D3.js force graph legend.
NODE_TYPE_COLORS: dict[str, str] = {
    "topic": "#4f9dff",
    "entity": "#27c2a0",
    "event": "#f5a623",
    "emotion": "#ff5d73",
    "audience": "#a06bff",
    "product": "#ffd166",
}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


@lru_cache(maxsize=1)
def load_seed_graph() -> dict[str, list[dict[str, Any]]]:
    """Load the cold-start seed nodes/edges as a plain dict.

    Returns ``{"nodes": [...], "edges": [...]}``; missing files yield empties.
    """
    nodes = _read_json(SEED_DIR / "seed_nodes.json").get("nodes", [])
    edges = _read_json(SEED_DIR / "seed_edges.json").get("edges", [])
    return {"nodes": list(nodes), "edges": list(edges)}


def _db_graph() -> dict[str, list[dict[str, Any]]] | None:
    """Return the persisted graph when ``DATABASE_URL`` is set and populated.

    Reads the ``graph_nodes`` / ``graph_edges`` tables via the raw-SQL
    GraphRepository. Returns ``None`` (so callers fall back to the seed graph)
    when no DB is configured, the tables are empty, or any error occurs — the
    dashboard must never 500 on a database problem.
    """
    url = os.getenv("DATABASE_URL")
    if not url:
        return None
    try:
        from database.db_adapter import DBAdapter
        from database.repositories.graph_repo import GraphRepository

        repo = GraphRepository(DBAdapter(url))
        try:
            graph = repo.as_graph()
        finally:
            repo.db.close()
        return graph if graph["nodes"] else None
    except Exception:  # noqa: BLE001 - dashboard must never 500 on DB issues
        return None


def _graph_source() -> dict[str, list[dict[str, Any]]]:
    """Live persisted graph when available, otherwise the cold-start seed graph."""
    return _db_graph() or load_seed_graph()


def graph_records() -> dict[str, list[dict[str, Any]]]:
    """Public accessor for the raw ``{nodes, edges}`` graph (DB-or-seed source).

    Used by exporters (e.g. the Obsidian bridge) that need the unprocessed
    node/edge records rather than the D3 ``graph_payload`` shape.
    """
    return _graph_source()


def graph_payload() -> dict[str, Any]:
    """Build a D3-friendly ``{nodes, links}`` payload with colour metadata."""
    graph = _graph_source()
    nodes = [
        {
            "id": n.get("id"),
            "name": n.get("name", n.get("id")),
            "type": n.get("type", "topic"),
            "weight": float(n.get("weight", 0.5)),
            "color": NODE_TYPE_COLORS.get(n.get("type", "topic"), "#8892a6"),
        }
        for n in graph["nodes"]
    ]
    links = [
        {
            "source": e.get("from_node"),
            "target": e.get("to_node"),
            "relation": e.get("relation_type", "related_to"),
            "weight": float(e.get("weight", 0.5)),
        }
        for e in graph["edges"]
    ]
    return {"nodes": nodes, "links": links}


def graph_stats() -> dict[str, Any]:
    """Summary counts for the dashboard: node/edge totals and type breakdown."""
    graph = _graph_source()
    nodes, edges = graph["nodes"], graph["edges"]
    by_type: dict[str, int] = {}
    for n in nodes:
        by_type[n.get("type", "unknown")] = by_type.get(n.get("type", "unknown"), 0) + 1
    by_relation: dict[str, int] = {}
    for e in edges:
        rel = e.get("relation_type", "unknown")
        by_relation[rel] = by_relation.get(rel, 0) + 1
    return {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes_by_type": dict(sorted(by_type.items())),
        "edges_by_relation": dict(sorted(by_relation.items())),
    }


def top_revenue_paths(limit: int = 5) -> list[dict[str, Any]]:
    """Rank ``monetizes_via`` seed edges as a stand-in for scored revenue paths.

    Replaced by the scoring_engine output once Phase 2 lands; until then this
    surfaces the highest-weight monetisation edges from the seed graph.
    """
    graph = _graph_source()
    name_by_id = {n.get("id"): n.get("name", n.get("id")) for n in graph["nodes"]}
    monetizing = [e for e in graph["edges"] if e.get("relation_type") == "monetizes_via"]
    monetizing.sort(key=lambda e: float(e.get("weight", 0)), reverse=True)
    return [
        {
            "source": name_by_id.get(e.get("from_node"), e.get("from_node")),
            "target": name_by_id.get(e.get("to_node"), e.get("to_node")),
            "weight": float(e.get("weight", 0)),
        }
        for e in monetizing[:limit]
    ]


def _safe_config(name: str) -> dict[str, Any]:
    """Load a config file, returning {} if PyYAML or the file is unavailable."""
    try:
        from utils.config_loader import load_config

        return load_config(name)
    except Exception:  # noqa: BLE001 - dashboard must never 500 on config issues
        return {}


def dashboard_summary() -> dict[str, Any]:
    """Top-level KPI tiles for the index page."""
    stats = graph_stats()
    settings = _safe_config("settings")
    app_cfg = settings.get("app", {}) if isinstance(settings, dict) else {}
    graph_cfg = settings.get("graph", {}) if isinstance(settings, dict) else {}
    return {
        "app_name": app_cfg.get("name", "iigp"),
        "app_version": app_cfg.get("version", "2.0.0"),
        "graph_backend": graph_cfg.get("graph_backend", "networkx"),
        "node_count": stats["node_count"],
        "edge_count": stats["edge_count"],
        "phase": "Phase 8 — Observability & Admin",
    }


def content_queue() -> list[dict[str, Any]]:
    """Representative content-factory review queue.

    The live queue is populated by the publisher/quality_gate in Phase 3; this
    placeholder mirrors that schema so the template and tests are stable.
    """
    paths = top_revenue_paths(limit=4)
    statuses = ["draft", "in_review", "approved", "published"]
    items: list[dict[str, Any]] = []
    for idx, path in enumerate(paths):
        items.append(
            {
                "id": f"content-{idx + 1:03d}",
                "title": f"{path['source']} → {path['target']}",
                "channel": ["blog", "youtube", "newsletter", "instagram"][idx % 4],
                "status": statuses[idx % len(statuses)],
                "quality_score": round(0.6 + path["weight"] * 0.4, 3),
            }
        )
    return items


def content_stats() -> dict[str, Any]:
    """Content generation stats — DB when populated, else seed fallback.

    Mirrors the ``_graph_source`` DB-or-seed pattern; never raises.
    """
    url = os.getenv("DATABASE_URL")
    if url:
        try:
            from database.db_adapter import DBAdapter
            from database.repositories.content_repo import ContentRepository

            repo = ContentRepository(DBAdapter(url))
            try:
                counts = repo.counts()
            finally:
                repo.db.close()
            if counts["total"] > 0:
                return counts
        except Exception:  # noqa: BLE001 - dashboard must never 500 on DB issues
            pass
    # Seed fallback: derive from the representative queue.
    items = content_queue()
    by_status: dict[str, int] = {}
    for item in items:
        by_status[item["status"]] = by_status.get(item["status"], 0) + 1
    return {"total": len(items), "by_status": dict(sorted(by_status.items()))}


def experiment_summary() -> list[dict[str, Any]]:
    """Representative A/B experiment rows (replaced by experiments/ in Phase 5)."""
    thresholds = _safe_config("thresholds")
    decision = thresholds.get("decision", {}) if isinstance(thresholds, dict) else {}
    significance = float(decision.get("significance_level", 0.05))
    return [
        {
            "experiment_id": "exp-headline-tone",
            "variant_a": "neutral",
            "variant_b": "surprise",
            "impressions": 12_400,
            "ctr_a": 0.031,
            "ctr_b": 0.047,
            "significance_level": significance,
            "status": "running",
        },
        {
            "experiment_id": "exp-publish-hour",
            "variant_a": "09:00 KST",
            "variant_b": "21:00 KST",
            "impressions": 8_900,
            "ctr_a": 0.052,
            "ctr_b": 0.041,
            "significance_level": significance,
            "status": "concluded",
        },
    ]


def settings_view() -> dict[str, Any]:
    """Read-only, secret-free snapshot of selected configuration for display."""
    settings = _safe_config("settings")
    weights = _safe_config("weights")
    view: dict[str, Any] = {}
    if isinstance(settings, dict):
        view["app"] = settings.get("app", {})
        view["graph_backend"] = settings.get("graph", {}).get("graph_backend")
        view["embedding_dim"] = settings.get("embeddings", {}).get("dim")
        view["orchestrator"] = settings.get("pipeline", {}).get("orchestrator")
    if isinstance(weights, dict):
        view["graph_score_weights"] = weights.get("graph_score", {})
        view["revenue_stream_weights"] = weights.get("revenue_stream_weights", {})
    return view


def _store_safe() -> Any:
    """Return the SQLite asset store, or None if unavailable (never raises)."""
    try:
        from database import db_store

        db_store.init_db()
        return db_store
    except Exception:  # noqa: BLE001 - dashboard must never 500 on DB issues
        return None


def _pct(actual: float, target: float) -> float:
    """Progress percentage of actual vs target, clamped to [0, 100]."""
    if target <= 0:
        return 0.0
    return round(min(100.0, max(0.0, actual / target * 100.0)), 1)


def os_dashboard() -> dict[str, Any]:
    """Management-console metrics: mission progress, ROI/budget, portfolio mix.

    Reads realised performance + cost from the SQLite asset store and the
    monthly targets from ``settings.yaml -> mission``. Degrades to zeros (with
    targets still shown) when the store or config is unavailable.
    """
    settings = _safe_config("settings")
    mission = settings.get("mission", {}) if isinstance(settings, dict) else {}
    revenue_target = float(mission.get("monthly_revenue_target_krw", 5_000_000) or 0)
    subscriber_target = int(mission.get("subscriber_target", 1000) or 0)
    budget_usd = float(mission.get("monthly_llm_budget_usd", 50.0) or 0)

    store = _store_safe()
    totals = store.feedback_totals() if store else {}
    revenue_actual = float(totals.get("revenue", 0.0))
    subscribers_actual = int(totals.get("subscribers", 0))
    cost_used = store.cost_total() if store else 0.0

    roi = round((revenue_actual / cost_used), 2) if cost_used > 0 else None

    # Deployments + calibrated-weights history (Phase 7).
    deployments = store.get_deployments(limit=10) if store else []
    deploy_mix = store.deployment_mix() if store else []
    # Newsletter publish history (deployments tagged 'newsletter').
    newsletter_history = (
        [d for d in store.get_deployments(limit=100) if d.get("platform") == "newsletter"][:10]
        if store
        else []
    )
    weights_history = store.get_weights_history(limit=20) if store else []
    current_weights = weights_history[-1]["weights"] if weights_history else {}

    # Generated content with a Suno audio track (HTML5 player on the dashboard).
    audio_assets = []
    visual_assets = []
    if store:
        _assets = store.list_generated_content(limit=20)
        audio_assets = [c for c in _assets if c.get("audio_url")]
        visual_assets = [c for c in _assets if c.get("image_url")]

    # Portfolio mix: share of generated assets by channel.
    mix_counts: dict[str, int] = {}
    for item in content_queue():
        mix_counts[item["channel"]] = mix_counts.get(item["channel"], 0) + 1
    total_assets = sum(mix_counts.values()) or 1
    portfolio = [
        {"channel": ch, "count": cnt, "share": round(cnt / total_assets * 100, 1)}
        for ch, cnt in sorted(mix_counts.items(), key=lambda kv: kv[1], reverse=True)
    ]

    return {
        "mission": {
            "revenue_target_krw": revenue_target,
            "revenue_actual_krw": revenue_actual,
            "revenue_pct": _pct(revenue_actual, revenue_target),
            "subscriber_target": subscriber_target,
            "subscribers_actual": subscribers_actual,
            "subscriber_pct": _pct(subscribers_actual, subscriber_target),
        },
        "finance": {
            "budget_usd": budget_usd,
            "cost_used_usd": round(cost_used, 4),
            "budget_remaining_usd": round(max(0.0, budget_usd - cost_used), 4),
            "budget_used_pct": _pct(cost_used, budget_usd),
            "revenue_actual_krw": revenue_actual,
            "roi": roi,
        },
        "portfolio": portfolio,
        "deployments": deployments,
        "deploy_mix": deploy_mix,
        "audio_assets": audio_assets,
        "visual_assets": visual_assets,
        "newsletter_history": newsletter_history,
        "weights_history": weights_history,
        "current_weights": current_weights,
        "feedback_samples": int(totals.get("samples", 0)),
    }
