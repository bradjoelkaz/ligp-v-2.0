"""Score propagation across graph edges (QA-010 / DD-006).

Propagates a node's influence to neighbours along weighted edges, up to a
configurable number of hops, with per-hop decay. Pure-Python; works on any
``GraphStore`` implementation via its ``get_neighbors`` plus internal edges.
"""

from __future__ import annotations

from utils.logger import get_logger

_log = get_logger(__name__)


class GraphPropagation:
    """Weighted, hop-limited, decaying score propagation."""

    def __init__(self, hop_decay: float = 0.5) -> None:
        if not 0.0 < hop_decay <= 1.0:
            raise ValueError("hop_decay must be in (0, 1]")
        self.hop_decay = hop_decay

    def _edges_from(self, graph_store, node_id: str) -> list[tuple[str, float]]:
        """Return (neighbor_id, edge_weight) pairs for outgoing edges."""
        adj = getattr(graph_store, "_adj", None)
        if adj is not None and node_id in adj:
            return [(e.to_node, float(e.weight)) for e in adj[node_id]]
        # Fallback for backends without _adj: unit weights.
        return [(nid, 1.0) for nid in graph_store.get_neighbors(node_id)]

    def propagate(self, graph_store, node_id: str, hops: int = 2) -> dict[str, float]:
        """Spread a unit of influence from ``node_id`` up to ``hops`` away.

        Returns a mapping of reachable node_id -> accumulated influence
        (excluding the source). Influence along a path is the product of edge
        weights times ``hop_decay`` per hop.
        """
        if graph_store.get_node(node_id) is None:
            raise KeyError(f"node not found: {node_id}")
        scores: dict[str, float] = {}
        # BFS frontier of (node, influence, depth)
        frontier: list[tuple[str, float, int]] = [(node_id, 1.0, 0)]
        while frontier:
            current, influence, depth = frontier.pop(0)
            if depth >= hops:
                continue
            for neighbor, weight in self._edges_from(graph_store, current):
                contributed = influence * weight * self.hop_decay
                if contributed <= 0:
                    continue
                scores[neighbor] = scores.get(neighbor, 0.0) + contributed
                frontier.append((neighbor, contributed, depth + 1))
        scores.pop(node_id, None)
        return scores

    def batch_propagate(self, graph_store, node_ids: list[str]) -> dict[str, dict[str, float]]:
        """Run :meth:`propagate` for many seed nodes."""
        return {nid: self.propagate(graph_store, nid) for nid in node_ids}
