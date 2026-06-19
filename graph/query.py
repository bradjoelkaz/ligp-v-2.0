"""Query layer over a GraphStore (Layer 5 helper).

Provides neighbour lookup, shortest path, subgraph extraction and score-ranked
retrieval. Pure-Python BFS/Dijkstra; works against the in-memory adjacency.
"""

from __future__ import annotations

import heapq
from typing import Any

from graph.graph_store import GraphStore
from utils.logger import get_logger

_log = get_logger(__name__)


class GraphQuery:
    """Read-only query helpers built on top of a GraphStore."""

    def __init__(self, graph_store: GraphStore) -> None:
        self.store = graph_store

    def _out_edges(self, node_id: str):
        adj = getattr(self.store, "_adj", {})
        return adj.get(node_id, [])

    def get_neighbors(
        self, node_id: str, relation: str | None = None, max_hops: int = 1
    ) -> list[dict[str, Any]]:
        """Return neighbours within ``max_hops``, optionally filtered by relation."""
        if self.store.get_node(node_id) is None:
            raise KeyError(f"node not found: {node_id}")
        results: dict[str, dict[str, Any]] = {}
        frontier: list[tuple[str, int]] = [(node_id, 0)]
        visited = {node_id}
        while frontier:
            current, depth = frontier.pop(0)
            if depth >= max_hops:
                continue
            for e in self._out_edges(current):
                if relation is not None and e.relation_type != relation:
                    continue
                if e.to_node not in results:
                    results[e.to_node] = {
                        "node_id": e.to_node,
                        "relation": e.relation_type,
                        "weight": e.weight,
                        "hops": depth + 1,
                    }
                if e.to_node not in visited:
                    visited.add(e.to_node)
                    frontier.append((e.to_node, depth + 1))
        return list(results.values())

    def shortest_path(self, src: str, dst: str) -> list[str]:
        """Dijkstra over inverse edge weight (stronger edge = shorter)."""
        if self.store.get_node(src) is None or self.store.get_node(dst) is None:
            raise KeyError("both src and dst must exist")
        if src == dst:
            return [src]
        # cost = 1 / weight so heavier edges are "closer".
        heap: list[tuple[float, str, list[str]]] = [(0.0, src, [src])]
        best: dict[str, float] = {src: 0.0}
        while heap:
            cost, node, path = heapq.heappop(heap)
            if node == dst:
                return path
            for e in self._out_edges(node):
                step = 1.0 / e.weight if e.weight > 0 else float("inf")
                new_cost = cost + step
                if new_cost < best.get(e.to_node, float("inf")):
                    best[e.to_node] = new_cost
                    heapq.heappush(heap, (new_cost, e.to_node, path + [e.to_node]))
        return []

    def subgraph(self, node_ids: list[str], include_edges: bool = True) -> dict[str, Any]:
        """Extract the induced subgraph for the given node ids."""
        id_set = set(node_ids)
        nodes = [self.store.get_node(nid) for nid in node_ids if self.store.get_node(nid)]
        edges: list[dict[str, Any]] = []
        if include_edges:
            for nid in id_set:
                for e in self._out_edges(nid):
                    if e.to_node in id_set:
                        edges.append(
                            {
                                "from_node": e.from_node,
                                "to_node": e.to_node,
                                "relation": e.relation_type,
                                "weight": e.weight,
                            }
                        )
        return {
            "nodes": [
                {"id": n.id, "type": n.type, "name": n.name, "weight": n.weight} for n in nodes
            ],
            "edges": edges,
        }

    def top_k_by_score(self, k: int = 50, min_score: float = 0.35) -> list[dict[str, Any]]:
        """Return up to ``k`` nodes whose ``attrs['score']`` >= ``min_score``.

        Falls back to node weight when no score has been attached yet.
        """
        scored: list[dict[str, Any]] = []
        nodes = getattr(self.store, "_nodes", {})
        for node in nodes.values():
            score = float(node.attrs.get("score", node.weight))
            if score >= min_score:
                scored.append({"node_id": node.id, "name": node.name, "score": score})
        scored.sort(key=lambda d: d["score"], reverse=True)
        return scored[:k]
