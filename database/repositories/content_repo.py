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
    content_id TEXT PRIMARY KEY,
    title      TEXT,
    body       TEXT,
    platform   TEXT,
    status     TEXT,
    payload    TEXT,
    created_at TEXT
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

    def update_status(self, content_id: str, status: str) -> None:
        self.db.execute("UPDATE content SET status = ? WHERE content_id = ?", (status, content_id))
