"""Event store (DD-007).

SQLite-backed event database. Events boost related nodes for a time window.
Event types: trending | seasonal | breaking | planned. Uses the stdlib
``sqlite3`` module (no external dependency); an in-memory DB (":memory:") is
the default for tests.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from typing import Any

from utils.helpers import utcnow_iso
from utils.logger import get_logger

_log = get_logger(__name__)

EVENT_TYPES = {"trending", "seasonal", "breaking", "planned"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id        TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    start_date      TEXT NOT NULL,
    end_date        TEXT NOT NULL,
    type            TEXT NOT NULL,
    tags            TEXT NOT NULL,
    boost_multiplier REAL NOT NULL DEFAULT 1.0,
    created_at      TEXT NOT NULL
);
"""


class EventDB:
    """CRUD + time/tag queries over the events table."""

    def __init__(self, path: str = ":memory:") -> None:
        self.path = path
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    @staticmethod
    def _to_row(event: dict[str, Any]) -> dict[str, Any]:
        etype = event.get("type", "trending")
        if etype not in EVENT_TYPES:
            raise ValueError(f"invalid event type: {etype}")
        return {
            "event_id": event.get("event_id") or str(uuid.uuid4()),
            "name": event["name"],
            "start_date": _iso(event["start_date"]),
            "end_date": _iso(event["end_date"]),
            "type": etype,
            "tags": json.dumps(sorted(event.get("tags", []))),
            "boost_multiplier": float(event.get("boost_multiplier", 1.0)),
            "created_at": event.get("created_at") or utcnow_iso(),
        }

    @staticmethod
    def _from_row(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["tags"] = json.loads(d["tags"])
        return d

    def insert(self, event: dict[str, Any]) -> str:
        row = self._to_row(event)
        self._conn.execute(
            "INSERT INTO events VALUES (:event_id,:name,:start_date,:end_date,:type,"
            ":tags,:boost_multiplier,:created_at)",
            row,
        )
        self._conn.commit()
        return row["event_id"]

    def upsert(self, event: dict[str, Any]) -> str:
        row = self._to_row(event)
        self._conn.execute(
            "INSERT INTO events VALUES (:event_id,:name,:start_date,:end_date,:type,"
            ":tags,:boost_multiplier,:created_at) "
            "ON CONFLICT(event_id) DO UPDATE SET name=:name,start_date=:start_date,"
            "end_date=:end_date,type=:type,tags=:tags,boost_multiplier=:boost_multiplier",
            row,
        )
        self._conn.commit()
        return row["event_id"]

    def get_active_events(self, at: datetime) -> list[dict[str, Any]]:
        at_iso = _iso(at)
        cur = self._conn.execute(
            "SELECT * FROM events WHERE start_date <= ? AND end_date >= ?", (at_iso, at_iso)
        )
        return [self._from_row(r) for r in cur.fetchall()]

    def get_by_tag(self, tag: str) -> list[dict[str, Any]]:
        cur = self._conn.execute("SELECT * FROM events")
        return [self._from_row(r) for r in cur.fetchall() if tag in json.loads(r["tags"])]

    def close(self) -> None:
        self._conn.close()


def _iso(value: Any) -> str:
    """Coerce datetime/str to ISO-8601 string."""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
