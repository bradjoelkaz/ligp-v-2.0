"""Cold-start bootstrap (QA-004).

Loads ``data/seed/seed_nodes.json`` and ``seed_edges.json`` into a GraphStore
when the graph is empty, so scoring/decision layers have structure to work with
before live ingestion produces enough data.
"""

from __future__ import annotations

import json
from pathlib import Path

from graph.edge_builder import build_edge
from graph.graph_store import Edge, GraphStore, Node, get_graph_store
from utils.config_loader import load_config
from utils.logger import get_logger

_log = get_logger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_NODES = _REPO_ROOT / "data" / "seed" / "seed_nodes.json"
_DEFAULT_EDGES = _REPO_ROOT / "data" / "seed" / "seed_edges.json"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_seed_nodes(store: GraphStore, path: Path | None = None) -> int:
    data = _load_json(path or _DEFAULT_NODES)
    count = 0
    for n in data.get("nodes", []):
        store.add_node(
            Node(
                id=n["id"],
                type=n["type"],
                name=n["name"],
                weight=float(n.get("weight", 1.0)),
                embedding=n.get("embedding"),
                created_at=n.get("created_at", ""),
            )
        )
        count += 1
    _log.info("seed_nodes_loaded", extra={"count": count})
    return count


def load_seed_edges(store: GraphStore, path: Path | None = None) -> int:
    data = _load_json(path or _DEFAULT_EDGES)
    count = 0
    for e in data.get("edges", []):
        edge: Edge = build_edge(
            e["from_node"], e["to_node"], e["relation_type"], weight=e.get("weight")
        )
        store.add_edge(edge)
        count += 1
    _log.info("seed_edges_loaded", extra={"count": count})
    return count


def bootstrap(store: GraphStore | None = None, force: bool = False) -> GraphStore:
    """Populate the graph from seed files if empty (or when ``force``)."""
    if store is None:
        try:
            backend = load_config("settings").get("graph", {}).get("graph_backend", "networkx")
        except Exception:  # pragma: no cover
            backend = "inmemory"
        store = get_graph_store(backend)

    if store.num_nodes() > 0 and not force:
        _log.info(
            "bootstrap_skipped", extra={"reason": "graph not empty", "nodes": store.num_nodes()}
        )
        return store

    n = load_seed_nodes(store)
    e = load_seed_edges(store)
    _log.info("bootstrap_complete", extra={"nodes": n, "edges": e})
    return store


if __name__ == "__main__":
    g = bootstrap(get_graph_store("inmemory"))
    print(f"bootstrapped graph: {g.num_nodes()} nodes, {g.num_edges()} edges")
