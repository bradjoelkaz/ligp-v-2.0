"""Database adapter (Layer 13).

A thin SQLite/PostgreSQL adapter selected by ``DATABASE_URL`` (or the
``sqlite_path`` in settings). SQLite uses the stdlib ``sqlite3`` with a single
persistent connection; PostgreSQL is opened lazily via ``psycopg`` (psycopg3)
and, when ``psycopg_pool`` is available, served from a
``psycopg_pool.ConnectionPool`` (the psycopg3 equivalent of psycopg2's
``ThreadedConnectionPool``) so high-concurrency API/worker traffic reuses
connections instead of paying a TCP+auth handshake per query and exhausting
sockets. The ``?`` placeholder style is normalized per backend.

Pool sizing is env-tunable (``DB_POOL_MIN_CONN`` default 5,
``DB_POOL_MAX_CONN`` default 20). Connections are always returned to the pool in
a ``finally`` block; a transaction holds a single connection for its duration
and returns it on exit.
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
        self._pool: Any | None = None
        self._tx_conn: Any | None = None
        self._in_transaction = False

    # -- connection -------------------------------------------------------- #
    def connect(self) -> None:
        """Open the single persistent connection (sqlite; postgres no-pool fallback)."""
        if self._conn is not None:
            return
        if self.backend == "sqlite":
            path = self.url.replace("sqlite:///", "") or ":memory:"
            self._conn = sqlite3.connect(path)
            self._conn.row_factory = sqlite3.Row
        else:  # pragma: no cover - requires psycopg + server
            import psycopg

            self._conn = psycopg.connect(self.url)

    def _get_pool(self) -> Any | None:
        """Lazily build the psycopg3 connection pool (postgres only).

        Returns ``None`` for sqlite, or when ``psycopg_pool`` is not installed
        (callers then fall back to a single persistent connection).
        """
        if self.backend != "postgres":
            return None
        if self._pool is not None:
            return self._pool
        try:
            from psycopg_pool import ConnectionPool
        except Exception:  # pragma: no cover - pool extra not installed -> fallback
            return None
        min_conn = int(os.environ.get("DB_POOL_MIN_CONN", "5"))
        max_conn = int(os.environ.get("DB_POOL_MAX_CONN", "20"))
        self._pool = ConnectionPool(self.url, min_size=min_conn, max_size=max_conn, open=True)
        # Register for scrape-time pool metrics (Phase 20); never fail on this.
        try:
            from api.metrics import register_db_pool

            register_db_pool(self._pool)
        except Exception:  # pragma: no cover - metrics wiring is best-effort
            pass
        _log.info(
            "db_pool_initialized",
            extra={"min": min_conn, "max": max_conn, "backend": self.backend},
        )
        return self._pool

    def _acquire(self) -> Any:
        """Get a connection: sqlite persistent, postgres from the pool (or fallback)."""
        if self.backend == "sqlite":
            self.connect()
            return self._conn
        # postgres: reuse the held connection inside a transaction
        if self._in_transaction and self._tx_conn is not None:
            return self._tx_conn
        pool = self._get_pool()
        if pool is None:  # pragma: no cover - no-pool single-conn fallback
            self.connect()
            return self._conn
        conn = pool.getconn()
        if self._in_transaction:
            self._tx_conn = conn
        return conn

    def _release(self, conn: Any) -> None:
        """Return a connection to the pool (no-op for sqlite / held transactions)."""
        if self.backend == "sqlite":
            return
        if self._in_transaction:
            return  # held until the transaction ends
        if self._pool is not None:
            self._pool.putconn(conn)

    def _normalize(self, query: str) -> str:
        # Postgres uses %s placeholders; sqlite uses ?.
        if self.backend == "postgres":
            return query.replace("?", "%s")
        return query

    # -- operations -------------------------------------------------------- #
    def execute(self, query: str, params: tuple = ()) -> list[dict[str, Any]]:
        """Execute a statement; return rows as dicts (empty for writes)."""
        conn = self._acquire()
        try:
            cur = conn.execute(self._normalize(query), params)
            rows: list[dict[str, Any]] = []
            if cur.description is not None:
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
            if not self._in_transaction:
                conn.commit()
            return rows
        finally:
            if not self._in_transaction:
                self._release(conn)

    def executemany(self, query: str, params: list[tuple]) -> None:
        conn = self._acquire()
        try:
            conn.executemany(self._normalize(query), params)
            if not self._in_transaction:
                conn.commit()
        finally:
            if not self._in_transaction:
                self._release(conn)

    @contextlib.contextmanager
    def transaction(self) -> Iterator[DBAdapter]:
        """Context manager: commit on success, rollback on exception.

        Holds a single connection for the whole transaction (so every nested
        ``execute`` runs on the same connection) and returns it to the pool on
        exit.
        """
        self._in_transaction = True
        conn = self._acquire()
        try:
            yield self
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._in_transaction = False
            if self.backend == "postgres" and self._tx_conn is not None:
                if self._pool is not None:
                    self._pool.putconn(self._tx_conn)
                self._tx_conn = None

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        if self._pool is not None:
            self._pool.close()
            self._pool = None
