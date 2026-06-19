"""Database adapter (Layer 13).

A thin SQLite/PostgreSQL adapter selected by ``DATABASE_URL`` (or the
``sqlite_path`` in settings). SQLite uses the stdlib ``sqlite3``; PostgreSQL is
opened lazily via ``psycopg`` only when a ``postgresql://`` URL is given. The
``?`` placeholder style is normalized per backend.
"""

from __future__ import annotations

import contextlib
import os
import sqlite3
from collections.abc import Iterator
from typing import Any

from utils.logger import get_logger

_log = get_logger(__name__)


class DBAdapter:
    """Minimal cross-backend DB wrapper."""

    def __init__(self, url: str | None = None) -> None:
        self.url = url or os.environ.get("DATABASE_URL") or "sqlite:///:memory:"
        self.backend = "postgres" if self.url.startswith("postgres") else "sqlite"
        self._conn: Any | None = None
        self._in_transaction = False

    # -- connection -------------------------------------------------------- #
    def connect(self) -> None:
        if self._conn is not None:
            return
        if self.backend == "sqlite":
            path = self.url.replace("sqlite:///", "") or ":memory:"
            self._conn = sqlite3.connect(path)
            self._conn.row_factory = sqlite3.Row
        else:  # pragma: no cover - requires psycopg + server
            import psycopg

            self._conn = psycopg.connect(self.url)

    def _normalize(self, query: str) -> str:
        # Postgres uses %s placeholders; sqlite uses ?.
        if self.backend == "postgres":  # pragma: no cover
            return query.replace("?", "%s")
        return query

    # -- operations -------------------------------------------------------- #
    def execute(self, query: str, params: tuple = ()) -> list[dict[str, Any]]:
        """Execute a statement; return rows as dicts (empty for writes)."""
        self.connect()
        assert self._conn is not None
        cur = self._conn.execute(self._normalize(query), params)
        rows: list[dict[str, Any]] = []
        if cur.description is not None:
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
        if not self._in_transaction:
            self._conn.commit()
        return rows

    def executemany(self, query: str, params: list[tuple]) -> None:
        self.connect()
        assert self._conn is not None
        self._conn.executemany(self._normalize(query), params)
        if not self._in_transaction:
            self._conn.commit()

    @contextlib.contextmanager
    def transaction(self) -> Iterator[DBAdapter]:
        """Context manager: commit on success, rollback on exception."""
        self.connect()
        assert self._conn is not None
        self._in_transaction = True
        try:
            yield self
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        finally:
            self._in_transaction = False

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
