"""Node repository (Layer 13).

Persists graph nodes and supports a brute-force cosine nearest-neighbour search
over stored embeddings (a real vector DB replaces this in production).
"""

from __future__ import annotations

import json
import math
from typing import Any

from database.db_adapter import DBAdapter
from utils.logger import get_logger

_log = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    node_id   TEXT PRIMARY KEY,
    type      TEXT,
    name      TEXT,
    weight    REAL,
    embedding TEXT
);
"""


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class NodeRepository:
    """Persist nodes and run nearest-neighbour search."""

    def __init__(self, db: DBAdapter) -> None:
        self.db = db
        self.db.execute(_SCHEMA)

    def upsert(self, node: dict[str, Any]) -> str:
        node_id = node["node_id"] if "node_id" in node else node["id"]
        self.db.execute(
            "INSERT INTO nodes (node_id,type,name,weight,embedding) VALUES (?,?,?,?,?) "
            "ON CONFLICT(node_id) DO UPDATE SET type=excluded.type,name=excluded.name,"
            "weight=excluded.weight,embedding=excluded.embedding",
            (
                node_id,
                node.get("type", ""),
                node.get("name", ""),
                float(node.get("weight", 1.0)),
                json.dumps(node.get("embedding")) if node.get("embedding") is not None else None,
            ),
        )
        return node_id

    def get(self, node_id: str) -> dict[str, Any] | None:
        rows = self.db.execute("SELECT * FROM nodes WHERE node_id = ?", (node_id,))
        return rows[0] if rows else None

    def search_by_embedding(self, embedding: list[float], top_k: int = 10) -> list[dict[str, Any]]:
        rows = self.db.execute("SELECT node_id, name, embedding FROM nodes", ())
        scored: list[dict[str, Any]] = []
        for row in rows:
            emb = json.loads(row["embedding"]) if row["embedding"] else None
            if emb is None:
                continue
            scored.append(
                {
                    "node_id": row["node_id"],
                    "name": row["name"],
                    "similarity": _cosine(embedding, emb),
                }
            )
        scored.sort(key=lambda d: d["similarity"], reverse=True)
        return scored[:top_k]
