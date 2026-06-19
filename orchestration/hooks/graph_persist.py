"""Pipeline -> DB graph persistence hook (Phase 9).

Syncs a ``GraphStore``'s current nodes/edges into the ``graph_nodes`` /
``graph_edges`` tables (via the raw-SQL ``GraphRepository``) so the admin graph
view reflects real pipeline output instead of only manually-added data.

Design rules:
- Fire-and-forget: a DB failure must NEVER stop the worker. Every DB access is
  wrapped and only logged.
- No-op (returns ``False``) when ``DATABASE_URL`` is unset.
- Lazy DB imports so this module stays importable without a database stack.
"""

from __future__ import annotations

import os
from typing import Any

from utils.logger import get_logger

_log = get_logger(__name__)


def persist_graph_to_db(graph_store: Any) -> bool:
    """Upsert ``graph_store``'s nodes/edges into the DB.

    Returns ``True`` on success, ``False`` on no-op (no ``DATABASE_URL``) or any
    error (which is swallowed and logged).
    """
    url = os.getenv("DATABASE_URL")
    if not url:
        return False
    try:
        from database.db_adapter import DBAdapter
        from database.repositories.graph_repo import GraphRepository

        repo = GraphRepository(DBAdapter(url))
        try:
            for node in graph_store.list_nodes():
                repo.upsert_node(
                    node["id"],
                    node.get("type", "topic"),
                    node.get("name", node["id"]),
                    float(node.get("weight", 1.0)),
                )
            for edge in graph_store.list_edges():
                repo.upsert_edge(
                    edge["from_node"],
                    edge["to_node"],
                    edge.get("relation_type", "related_to"),
                    float(edge.get("weight", 0.5)),
                )
        finally:
            repo.db.close()
        return True
    except Exception:  # noqa: BLE001 - persistence must never crash the worker
        _log.exception("graph_persist_failed")
        return False
