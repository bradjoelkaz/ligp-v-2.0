"""Content repository (Layer 13)."""

from __future__ import annotations

import json
import uuid
from typing import Any

from database.db_adapter import DBAdapter
from utils.helpers import utcnow_iso
from utils.logger import get_logger

_log = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS content (
    content_id    TEXT PRIMARY KEY,
    node_id       TEXT,
    platform      TEXT,
    status        TEXT DEFAULT 'draft',
    title         TEXT,
    body          TEXT,
    payload       TEXT,
    tags          TEXT,
    quality_score REAL,
    published_url TEXT,
    published_at  TIMESTAMP,
    generator     TEXT,
    llm_cost_usd  REAL DEFAULT 0.0,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


class ContentRepository:
    """Persist and query generated content."""

    def __init__(self, db: DBAdapter) -> None:
        self.db = db
        self.db.execute(_SCHEMA)

    def save(self, content: dict[str, Any]) -> str:
        content_id = content.get("content_id") or str(uuid.uuid4())
        self.db.execute(
            "INSERT INTO content (content_id,title,body,platform,status,payload,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                content_id,
                content.get("title", ""),
                content.get("body", ""),
                content.get("platform", ""),
                content.get("status", "draft"),
                json.dumps(content, ensure_ascii=False, default=str),
                utcnow_iso(),
            ),
        )
        return content_id

    def get(self, content_id: str) -> dict[str, Any] | None:
        rows = self.db.execute("SELECT * FROM content WHERE content_id = ?", (content_id,))
        return rows[0] if rows else None

    def list_by_status(self, status: str, limit: int = 100) -> list[dict[str, Any]]:
        return self.db.execute(
            "SELECT * FROM content WHERE status = ? ORDER BY created_at DESC LIMIT ?",
            (status, limit),
        )

    def update_status(
        self,
        content_id: str,
        status: str,
        result: str | None = None,
        error: str | None = None,
    ) -> None:
        """Update status; optionally store a result/error JSON into ``payload``.

        ``payload`` is only overwritten when ``result`` or ``error`` is provided
        (COALESCE keeps the existing payload otherwise), so plain status updates
        remain non-destructive.
        """
        self.db.execute(
            "UPDATE content SET status = ?, payload = COALESCE(?, payload), "
            "updated_at = CURRENT_TIMESTAMP WHERE content_id = ?",
            (status, result if result is not None else error, content_id),
        )

    def list_content(
        self, limit: int = 50, status: str | None = None, since: str | None = None
    ) -> list[dict[str, Any]]:
        """List content history with optional status/since filters (newest first)."""
        sql = (
            "SELECT content_id, title, status, platform, created_at, updated_at "
            "FROM content WHERE 1=1"
        )
        params: list[Any] = []
        if status:
            sql += " AND status = ?"
            params.append(status)
        if since:
            sql += " AND created_at >= ?"
            params.append(since)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(int(limit))
        return self.db.execute(sql, tuple(params))

    def counts(self) -> dict[str, Any]:
        """Return total content count and a per-status breakdown."""
        total = self.db.execute("SELECT COUNT(*) AS c FROM content", ())[0]["c"]
        rows = self.db.execute("SELECT status, COUNT(*) AS c FROM content GROUP BY status", ())
        by_status = {row["status"]: int(row["c"]) for row in rows}
        return {"total": int(total), "by_status": dict(sorted(by_status.items()))}
