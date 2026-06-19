"""Graph repository (Layer 13 / Phase 9).

Persists the knowledge graph (nodes + edges) for the admin dashboard so the
graph view reflects live, durable data instead of the cold-start seed. Uses the
same raw-SQL ``DBAdapter`` pattern as :mod:`database.repositories.node_repo`,
so it runs on both SQLite (dev/tests, stdlib ``sqlite3``) and PostgreSQL
(production, lazy ``psycopg``) without an ORM.

Dedicated ``graph_nodes`` / ``graph_edges`` tables are used (rather than the
``nodes`` / ``edges`` tables in migration 001) to keep this feature isolated
and consistent across the SQLite and Postgres backends.
"""

from __future__ import annotations

from typing import Any

from database.db_adapter import DBAdapter
from utils.logger import get_logger

_log = get_logger(__name__)

_SCHEMA_NODES = """
CREATE TABLE IF NOT EXISTS graph_nodes (
    node_id TEXT PRIMARY KEY,
    type    TEXT,
    name    TEXT,
    weight  REAL
);
"""

_SCHEMA_EDGES = """
CREATE TABLE IF NOT EXISTS graph_edges (
    edge_id       TEXT PRIMARY KEY,
    from_node     TEXT,
    to_node       TEXT,
    relation_type TEXT,
    weight        REAL
);
"""


def _edge_id(from_node: str, to_node: str, relation_type: str) -> str:
    return f"{from_node}->{to_node}:{relation_type}"


class GraphRepository:
    """Persist and query graph nodes/edges via the shared ``DBAdapter``."""

    def __init__(self, db: DBAdapter) -> None:
        self.db = db
        self.db.execute(_SCHEMA_NODES)
        self.db.execute(_SCHEMA_EDGES)

    # -- writes ----------------------------------------------------------- #
    def upsert_node(
        self, node_id: str, type: str = "topic", name: str = "", weight: float = 1.0
    ) -> str:
        self.db.execute(
            "INSERT INTO graph_nodes (node_id,type,name,weight) VALUES (?,?,?,?) "
            "ON CONFLICT(node_id) DO UPDATE SET type=excluded.type,name=excluded.name,"
            "weight=excluded.weight",
            (node_id, type, name or node_id, float(weight)),
        )
        return node_id

    def upsert_edge(
        self, from_node: str, to_node: str, relation_type: str = "related_to", weight: float = 0.5
    ) -> str:
        edge_id = _edge_id(from_node, to_node, relation_type)
        self.db.execute(
            "INSERT INTO graph_edges (edge_id,from_node,to_node,relation_type,weight) "
            "VALUES (?,?,?,?,?) ON CONFLICT(edge_id) DO UPDATE SET weight=excluded.weight",
            (edge_id, from_node, to_node, relation_type, float(weight)),
        )
        return edge_id

    # -- reads ------------------------------------------------------------ #
    def get_node(self, node_id: str) -> dict[str, Any] | None:
        rows = self.db.execute(
            "SELECT node_id AS id, type, name, weight FROM graph_nodes WHERE node_id = ?",
            (node_id,),
        )
        return rows[0] if rows else None

    def fetch_nodes(self) -> list[dict[str, Any]]:
        """Return nodes in the seed-graph shape: ``{id,type,name,weight}``."""
        return self.db.execute("SELECT node_id AS id, type, name, weight FROM graph_nodes", ())

    def fetch_edges(self) -> list[dict[str, Any]]:
        """Return edges in the seed-graph shape: ``{from_node,to_node,relation_type,weight}``."""
        return self.db.execute(
            "SELECT from_node, to_node, relation_type, weight FROM graph_edges", ()
        )

    def as_graph(self) -> dict[str, list[dict[str, Any]]]:
        """Return ``{"nodes": [...], "edges": [...]}`` (same shape as the seed loader)."""
        return {"nodes": self.fetch_nodes(), "edges": self.fetch_edges()}

    def counts(self) -> tuple[int, int]:
        n = self.db.execute("SELECT COUNT(*) AS c FROM graph_nodes", ())[0]["c"]
        e = self.db.execute("SELECT COUNT(*) AS c FROM graph_edges", ())[0]["c"]
        return int(n), int(e)
