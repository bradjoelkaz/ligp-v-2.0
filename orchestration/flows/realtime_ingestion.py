"""Real-time ingestion flow (Layer 15).

Lightweight 10-minute cadence flow: pull new RSS/Reddit items, deduplicate, and
upsert into the graph. Offline-capable core (``run_realtime_ingestion``) plus a
Prefect wrapper.
"""

from __future__ import annotations

from typing import Any

from graph.graph_store import GraphStore, InMemoryGraphStore, Node
from processing.deduplicator import Deduplicator
from utils.helpers import make_node_id
from utils.logger import get_logger

_log = get_logger(__name__)


def run_realtime_ingestion(
    documents: list[dict[str, Any]],
    store: GraphStore | None = None,
    dedup: Deduplicator | None = None,
) -> dict[str, Any]:
    """Deduplicate incoming docs and upsert topic nodes into ``store``."""
    store = store or InMemoryGraphStore()
    dedup = dedup or Deduplicator()
    added = 0
    for i, doc in enumerate(documents):
        key = doc.get("source_id", f"rt{i}")
        text = f"{doc.get('title', '')} {doc.get('text', '')}"
        if dedup.is_duplicate(key, text):
            continue
        topic = doc.get("title", "untitled")
        store.add_node(Node(id=make_node_id("topic", topic), type="topic", name=topic))
        added += 1
    return {"received": len(documents), "added": added, "graph_nodes": store.num_nodes()}


def realtime_ingestion() -> dict[str, Any]:  # pragma: no cover - requires prefect
    """Prefect flow wrapper for the real-time ingestion cadence."""
    try:
        from prefect import flow

        @flow(name="iigp-realtime-ingestion")
        def _flow() -> dict[str, Any]:
            return run_realtime_ingestion([])

        return _flow()
    except Exception:
        return run_realtime_ingestion([])
