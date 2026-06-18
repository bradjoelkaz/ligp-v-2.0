"""Delta-based graph snapshots with rollback (QA-010).

Keeps the most recent ``keep_versions`` snapshots (default 7 from
``settings.yaml -> graph.versioning.keep_versions``). Each snapshot stores the
full node/edge set plus a delta against its parent for cheap diffing and
rollback.
"""

from __future__ import annotations

import copy
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

from graph.graph_store import Edge, GraphStore, Node
from utils.config_loader import load_config
from utils.helpers import utcnow_iso
from utils.logger import get_logger

_log = get_logger(__name__)


@lru_cache(maxsize=1)
def _keep_versions() -> int:
    try:
        return int(
            load_config("settings").get("graph", {}).get("versioning", {}).get("keep_versions", 7)
        )
    except Exception:  # pragma: no cover
        return 7


def _snapshot_state(store: GraphStore) -> tuple[dict[str, Node], list[Edge]]:
    nodes = dict(getattr(store, "_nodes", {}))
    adj = getattr(store, "_adj", {})
    edges: list[Edge] = [e for elist in adj.values() for e in elist]
    return copy.deepcopy(nodes), copy.deepcopy(edges)


@dataclass
class Snapshot:
    snapshot_id: str
    label: str
    created_at: str
    parent: str | None
    nodes: dict[str, Node]
    edges: list[Edge]
    delta_nodes: list[str] = field(default_factory=list)
    delta_edges: list[str] = field(default_factory=list)


class GraphVersioning:
    """Maintains a bounded history of graph snapshots."""

    def __init__(self, keep_versions: int | None = None) -> None:
        self.keep_versions = keep_versions or _keep_versions()
        self._snapshots: deque[Snapshot] = deque(maxlen=self.keep_versions)
        self._counter = 0

    def _latest(self) -> Snapshot | None:
        return self._snapshots[-1] if self._snapshots else None

    @staticmethod
    def _edge_key(e: Edge) -> str:
        return f"{e.from_node}->{e.to_node}:{e.relation_type}"

    def create_snapshot(self, graph_store: GraphStore, label: str) -> str:
        """Capture the current graph state and return the new snapshot id."""
        nodes, edges = _snapshot_state(graph_store)
        parent = self._latest()
        self._counter += 1
        snap_id = f"v{self._counter}-{datetime.now(tz=UTC).strftime('%Y%m%d%H%M%S')}"

        delta_nodes: list[str] = []
        delta_edges: list[str] = []
        if parent is not None:
            parent_nodes = set(parent.nodes)
            delta_nodes = [nid for nid in nodes if nid not in parent_nodes]
            parent_edges = {self._edge_key(e) for e in parent.edges}
            delta_edges = [
                self._edge_key(e) for e in edges if self._edge_key(e) not in parent_edges
            ]

        snap = Snapshot(
            snapshot_id=snap_id,
            label=label,
            created_at=utcnow_iso(),
            parent=parent.snapshot_id if parent else None,
            nodes=nodes,
            edges=edges,
            delta_nodes=delta_nodes,
            delta_edges=delta_edges,
        )
        self._snapshots.append(snap)
        _log.info(
            "snapshot_created",
            extra={"snapshot_id": snap_id, "nodes": len(nodes), "edges": len(edges)},
        )
        return snap_id

    def list_snapshots(self) -> list[dict[str, Any]]:
        """Return snapshot metadata, newest last."""
        return [
            {
                "snapshot_id": s.snapshot_id,
                "label": s.label,
                "created_at": s.created_at,
                "parent": s.parent,
                "num_nodes": len(s.nodes),
                "num_edges": len(s.edges),
                "delta_nodes": len(s.delta_nodes),
                "delta_edges": len(s.delta_edges),
            }
            for s in self._snapshots
        ]

    def _get(self, snapshot_id: str) -> Snapshot:
        for s in self._snapshots:
            if s.snapshot_id == snapshot_id:
                return s
        raise KeyError(f"snapshot not found (may have been evicted): {snapshot_id}")

    def rollback(self, graph_store: GraphStore, snapshot_id: str) -> None:
        """Restore ``graph_store`` to the given snapshot's state in place."""
        snap = self._get(snapshot_id)
        if not hasattr(graph_store, "_nodes"):
            raise TypeError("rollback requires an in-memory-style GraphStore")
        graph_store._nodes = copy.deepcopy(snap.nodes)  # type: ignore[attr-defined]
        graph_store._adj = {nid: [] for nid in snap.nodes}  # type: ignore[attr-defined]
        graph_store._in = {nid: [] for nid in snap.nodes}  # type: ignore[attr-defined]
        for e in snap.edges:
            graph_store._adj.setdefault(e.from_node, []).append(copy.deepcopy(e))  # type: ignore[attr-defined]
            graph_store._in.setdefault(e.to_node, []).append(copy.deepcopy(e))  # type: ignore[attr-defined]
        _log.info("rollback_complete", extra={"snapshot_id": snapshot_id})

    def diff(self, snap_a: str, snap_b: str) -> dict[str, Any]:
        """Return added/removed nodes and edges going from snap_a -> snap_b."""
        a = self._get(snap_a)
        b = self._get(snap_b)
        a_nodes, b_nodes = set(a.nodes), set(b.nodes)
        a_edges = {self._edge_key(e) for e in a.edges}
        b_edges = {self._edge_key(e) for e in b.edges}
        return {
            "added_nodes": sorted(b_nodes - a_nodes),
            "removed_nodes": sorted(a_nodes - b_nodes),
            "added_edges": sorted(b_edges - a_edges),
            "removed_edges": sorted(a_edges - b_edges),
        }
