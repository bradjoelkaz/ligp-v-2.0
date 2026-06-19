"""GraphStore adapter pattern (DD-006 / QA-008).

A single ``GraphStore`` interface lets the rest of the system stay agnostic to
the backend. Phase 1 ships a pure-Python ``InMemoryGraphStore`` (no external
deps, fully testable) and a ``NetworkXGraphStore`` (lazy import). Neo4j /
TigerGraph backends implement the same interface in later phases and are
selected via ``settings.yaml -> graph.graph_backend``.

Node / Edge schemas follow the ERD in the master directive.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any

from utils.helpers import utcnow_iso

NODE_TYPES = {"topic", "entity", "event", "emotion", "audience", "product"}
RELATION_TYPES = {
    "related_to",
    "causes",
    "similar_to",
    "leads_to",
    "monetizes_via",
    "triggers_emotion",
    "belongs_to_event",
}


@dataclass
class Node:
    id: str
    type: str
    name: str
    weight: float = 1.0
    embedding: list[float] | None = None
    created_at: str = field(default_factory=utcnow_iso)
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class Edge:
    from_node: str
    to_node: str
    relation_type: str
    weight: float = 0.5
    attrs: dict[str, Any] = field(default_factory=dict)


class GraphStore(abc.ABC):
    """Backend-agnostic graph interface."""

    @abc.abstractmethod
    def add_node(self, node: Node) -> None: ...

    @abc.abstractmethod
    def add_edge(self, edge: Edge) -> None: ...

    @abc.abstractmethod
    def get_node(self, node_id: str) -> Node | None: ...

    @abc.abstractmethod
    def get_neighbors(self, node_id: str) -> list[str]: ...

    @abc.abstractmethod
    def compute_centrality(self) -> dict[str, float]: ...

    @abc.abstractmethod
    def num_nodes(self) -> int: ...

    @abc.abstractmethod
    def num_edges(self) -> int: ...

    @abc.abstractmethod
    def list_nodes(self) -> list[dict[str, Any]]: ...

    @abc.abstractmethod
    def list_edges(self) -> list[dict[str, Any]]: ...


class InMemoryGraphStore(GraphStore):
    """Pure-Python adjacency-list backend (Phase 1 default for tests/small graphs)."""

    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}
        self._adj: dict[str, list[Edge]] = {}
        self._in: dict[str, list[Edge]] = {}

    def add_node(self, node: Node) -> None:
        if node.type not in NODE_TYPES:
            raise ValueError(f"invalid node type: {node.type}")
        existing = self._nodes.get(node.id)
        if existing is None:
            self._nodes[node.id] = node
            self._adj.setdefault(node.id, [])
            self._in.setdefault(node.id, [])
        else:
            # Idempotent upsert: keep max weight, fill embedding if missing.
            existing.weight = max(existing.weight, node.weight)
            if existing.embedding is None and node.embedding is not None:
                existing.embedding = node.embedding

    def add_edge(self, edge: Edge) -> None:
        if edge.relation_type not in RELATION_TYPES:
            raise ValueError(f"invalid relation type: {edge.relation_type}")
        if edge.from_node not in self._nodes or edge.to_node not in self._nodes:
            raise KeyError("both endpoints must exist before adding an edge")
        # De-dup identical edges; keep the stronger weight.
        for e in self._adj[edge.from_node]:
            if e.to_node == edge.to_node and e.relation_type == edge.relation_type:
                e.weight = max(e.weight, edge.weight)
                return
        self._adj[edge.from_node].append(edge)
        self._in[edge.to_node].append(edge)

    def get_node(self, node_id: str) -> Node | None:
        return self._nodes.get(node_id)

    def get_neighbors(self, node_id: str) -> list[str]:
        return [e.to_node for e in self._adj.get(node_id, [])]

    def compute_centrality(self, damping: float = 0.85, iterations: int = 50) -> dict[str, float]:
        """Weighted PageRank (power iteration). Matches settings.yaml default."""
        nodes = list(self._nodes)
        n = len(nodes)
        if n == 0:
            return {}
        rank = dict.fromkeys(nodes, 1.0 / n)
        out_weight = {nid: sum(e.weight for e in self._adj.get(nid, [])) for nid in nodes}
        for _ in range(iterations):
            new_rank = dict.fromkeys(nodes, (1.0 - damping) / n)
            dangling = damping * sum(rank[nid] for nid in nodes if out_weight[nid] == 0) / n
            for nid in nodes:
                new_rank[nid] += dangling
            for nid in nodes:
                ow = out_weight[nid]
                if ow == 0:
                    continue
                share = damping * rank[nid] / ow
                for e in self._adj[nid]:
                    new_rank[e.to_node] += share * e.weight
            rank = new_rank
        total = sum(rank.values()) or 1.0
        return {k: v / total for k, v in rank.items()}

    def num_nodes(self) -> int:
        return len(self._nodes)

    def num_edges(self) -> int:
        return sum(len(v) for v in self._adj.values())

    def list_nodes(self) -> list[dict[str, Any]]:
        return [
            {"id": n.id, "type": n.type, "name": n.name, "weight": n.weight}
            for n in self._nodes.values()
        ]

    def list_edges(self) -> list[dict[str, Any]]:
        return [
            {
                "from_node": e.from_node,
                "to_node": e.to_node,
                "relation_type": e.relation_type,
                "weight": e.weight,
            }
            for edges in self._adj.values()
            for e in edges
        ]


class NetworkXGraphStore(GraphStore):
    """NetworkX-backed store for Phase 1 graphs up to ~100k nodes (DD-006)."""

    def __init__(self) -> None:
        try:
            import networkx as nx  # lazy optional import
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("networkx is required for NetworkXGraphStore") from exc
        self._nx = nx
        self._g = nx.DiGraph()

    def add_node(self, node: Node) -> None:
        if node.type not in NODE_TYPES:
            raise ValueError(f"invalid node type: {node.type}")
        self._g.add_node(node.id, **{"obj": node})

    def add_edge(self, edge: Edge) -> None:
        if edge.relation_type not in RELATION_TYPES:
            raise ValueError(f"invalid relation type: {edge.relation_type}")
        self._g.add_edge(
            edge.from_node, edge.to_node, weight=edge.weight, relation=edge.relation_type
        )

    def get_node(self, node_id: str) -> Node | None:
        data = self._g.nodes.get(node_id)
        return data.get("obj") if data else None

    def get_neighbors(self, node_id: str) -> list[str]:
        return list(self._g.successors(node_id)) if node_id in self._g else []

    def compute_centrality(self) -> dict[str, float]:
        return self._nx.pagerank(self._g, weight="weight") if self._g.number_of_nodes() else {}

    def num_nodes(self) -> int:
        return self._g.number_of_nodes()

    def num_edges(self) -> int:
        return self._g.number_of_edges()

    def list_nodes(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for nid, data in self._g.nodes(data=True):
            obj = data.get("obj")
            if obj is None:
                continue
            out.append({"id": nid, "type": obj.type, "name": obj.name, "weight": obj.weight})
        return out

    def list_edges(self) -> list[dict[str, Any]]:
        return [
            {
                "from_node": u,
                "to_node": v,
                "relation_type": d.get("relation", "related_to"),
                "weight": d.get("weight", 0.5),
            }
            for u, v, d in self._g.edges(data=True)
        ]


def get_graph_store(backend: str = "networkx") -> GraphStore:
    """Factory selecting the backend from ``settings.yaml -> graph.graph_backend``."""
    backend = (backend or "networkx").lower()
    if backend == "inmemory":
        return InMemoryGraphStore()
    if backend == "networkx":
        try:
            return NetworkXGraphStore()
        except RuntimeError:
            # Graceful fallback so the pipeline still runs without networkx.
            return InMemoryGraphStore()
    raise NotImplementedError(f"graph backend not available in Phase 1: {backend}")
