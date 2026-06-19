"""Unit tests for the DBAdapter PostgreSQL connection pool (Phase 18).

``psycopg_pool`` is not installed in the offline sandbox, so a fake module is
injected into ``sys.modules``; this lets us exercise the postgres pooled path
(getconn/putconn, sizing, transaction hold, close) deterministically without a
real Postgres server. The sqlite path must remain pool-free.
"""

from __future__ import annotations

import sys
import types

import pytest

from database.db_adapter import DBAdapter


class _FakeCursor:
    description = None

    def fetchall(self):  # pragma: no cover - never called (description is None)
        return []


class _FakeConn:
    def __init__(self):
        self.committed = 0
        self.rolled_back = 0

    def execute(self, query, params=()):
        return _FakeCursor()

    def commit(self):
        self.committed += 1

    def rollback(self):  # pragma: no cover - exercised in rollback test
        self.rolled_back += 1


class _FakePool:
    """Records construction args and hands out / takes back fake connections."""

    instances: list = []

    def __init__(self, conninfo, min_size=1, max_size=10, open=True):
        self.conninfo = conninfo
        self.min_size = min_size
        self.max_size = max_size
        self.opened = open
        self.checked_out = 0
        self.returned = 0
        self.closed = False
        self._conn = _FakeConn()
        _FakePool.instances.append(self)

    def getconn(self):
        self.checked_out += 1
        return self._conn

    def putconn(self, conn):
        self.returned += 1

    def close(self):
        self.closed = True


@pytest.fixture()
def fake_pool(monkeypatch):
    _FakePool.instances.clear()
    fake_mod = types.ModuleType("psycopg_pool")
    fake_mod.ConnectionPool = _FakePool
    monkeypatch.setitem(sys.modules, "psycopg_pool", fake_mod)
    return _FakePool


@pytest.mark.unit
def test_sqlite_uses_no_pool():
    db = DBAdapter("sqlite:///:memory:")
    assert db.backend == "sqlite"
    assert db._get_pool() is None


@pytest.mark.unit
def test_postgres_initializes_pool_with_defaults(fake_pool, monkeypatch):
    monkeypatch.delenv("DB_POOL_MIN_CONN", raising=False)
    monkeypatch.delenv("DB_POOL_MAX_CONN", raising=False)
    db = DBAdapter("postgresql://user:pw@localhost:5432/iigp")
    assert db.backend == "postgres"
    pool = db._get_pool()
    assert isinstance(pool, fake_pool)
    assert pool.min_size == 5 and pool.max_size == 20
    assert pool.conninfo == "postgresql://user:pw@localhost:5432/iigp"
    # Cached: a second call returns the same instance (no re-init).
    assert db._get_pool() is pool
    assert len(fake_pool.instances) == 1


@pytest.mark.unit
def test_pool_sizing_env_override(fake_pool, monkeypatch):
    monkeypatch.setenv("DB_POOL_MIN_CONN", "2")
    monkeypatch.setenv("DB_POOL_MAX_CONN", "8")
    db = DBAdapter("postgres://localhost/iigp")
    pool = db._get_pool()
    assert pool.min_size == 2 and pool.max_size == 8


@pytest.mark.unit
def test_execute_checks_out_and_returns_connection(fake_pool):
    db = DBAdapter("postgresql://localhost/iigp")
    db.execute("INSERT INTO t VALUES (?)", ("x",))
    pool = fake_pool.instances[0]
    assert pool.checked_out == 1
    assert pool.returned == 1  # returned in finally (no leak)
    assert pool._conn.committed == 1  # autocommit per statement


@pytest.mark.unit
def test_transaction_holds_one_connection(fake_pool):
    db = DBAdapter("postgresql://localhost/iigp")
    with db.transaction() as tx:
        tx.execute("INSERT INTO t VALUES (?)", ("a",))
        tx.execute("INSERT INTO t VALUES (?)", ("b",))
    pool = fake_pool.instances[0]
    # One checkout for the whole transaction, one return on exit.
    assert pool.checked_out == 1
    assert pool.returned == 1
    assert pool._conn.committed == 1  # single commit at transaction end


@pytest.mark.unit
def test_placeholder_normalized_for_postgres(fake_pool):
    db = DBAdapter("postgresql://localhost/iigp")
    assert db._normalize("SELECT * FROM t WHERE id=?") == "SELECT * FROM t WHERE id=%s"


@pytest.mark.unit
def test_close_closes_pool(fake_pool):
    db = DBAdapter("postgresql://localhost/iigp")
    db._get_pool()
    db.close()
    pool = fake_pool.instances[0]
    assert pool.closed is True
    assert db._pool is None
