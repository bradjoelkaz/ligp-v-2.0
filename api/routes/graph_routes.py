"""Graph API routes (Layer 14). Lazy FastAPI via factory."""

from __future__ import annotations

from typing import Any

from utils.logger import get_logger

_log = get_logger(__name__)


def get_router(graph_store: Any | None = None):  # pragma: no cover - requires fastapi
    """Build the graph APIRouter against an optional shared GraphStore."""
    from fastapi import APIRouter, HTTPException

    from graph.graph_store import get_graph_store
    from graph.query import GraphQuery

    store = graph_store or get_graph_store("inmemory")
    router = APIRouter(prefix="/graph", tags=["graph"])

    @router.get("/node/{node_id}")
    def get_node(node_id: str) -> dict[str, Any]:
        node = store.get_node(node_id)
        if node is None:
            raise HTTPException(status_code=404, detail="node not found")
        return {"id": node.id, "type": node.type, "name": node.name, "weight": node.weight}

    @router.get("/query/top")
    def top_k(k: int = 50, min_score: float = 0.35) -> list[dict[str, Any]]:
        return GraphQuery(store).top_k_by_score(k=k, min_score=min_score)

    return router
