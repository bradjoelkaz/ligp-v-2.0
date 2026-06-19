"""Unit tests for scrape-time dynamic metrics (Phase 20).

Covers the DB connection-pool gauges and the Celery queue-length gauge that are
refreshed on each ``/metrics`` render, plus their failure resilience. Gated on
``prometheus_client`` (offline dev skips; CI runs it). DB pools and the ``redis``
client are faked, so no real Postgres/Redis is needed.
"""

from __future__ import annotations

import sys
import types
import weakref

import pytest

pytest.importorskip("prometheus_client")

from prometheus_client import CollectorRegistry  # noqa: E402

from api import metrics as metrics_mod  # noqa: E402


def _fresh_metrics() -> metrics_mod._Metrics:
    m = metrics_mod._Metrics()
    m.setup(CollectorRegistry())
    return m


class _FakePool:
    def __init__(self, stats: dict):
        self._stats = stats

    def pop_stats(self) -> dict:
        return self._stats


def _fake_redis_module(llen_value=None, raise_exc=None):
    mod = types.ModuleType("redis")

    class _Client:
        def llen(self, name):
            return llen_value

    def from_url(*args, **kwargs):
        if raise_exc is not None:
            raise raise_exc
        return _Client()

    mod.Redis = type("Redis", (), {"from_url": staticmethod(from_url)})
    return mod


@pytest.fixture(autouse=True)
def _isolate_pools(monkeypatch):
    """Each test gets a clean pool registry."""
    monkeypatch.setattr(metrics_mod, "_DB_POOLS", weakref.WeakSet())


@pytest.mark.unit
def test_pool_active_derived_from_size_available(monkeypatch):
    pool = _FakePool({"pool_size": 10, "pool_available": 3})
    metrics_mod.register_db_pool(pool)
    m = _fresh_metrics()
    m.update_dynamic()
    assert m.registry.get_sample_value("iigp_db_pool_connections_active") == 7.0
    assert m.registry.get_sample_value("iigp_db_pool_connections_total") == 10.0


@pytest.mark.unit
def test_pool_active_uses_connections_in_use_when_present(monkeypatch):
    pool = _FakePool({"connections_in_use": 4, "pool_size": 12})
    metrics_mod.register_db_pool(pool)
    m = _fresh_metrics()
    m.update_dynamic()
    assert m.registry.get_sample_value("iigp_db_pool_connections_active") == 4.0
    assert m.registry.get_sample_value("iigp_db_pool_connections_total") == 12.0


@pytest.mark.unit
def test_pool_stats_sum_across_pools(monkeypatch):
    metrics_mod.register_db_pool(_FakePool({"pool_size": 5, "pool_available": 2}))
    metrics_mod.register_db_pool(_FakePool({"pool_size": 8, "pool_available": 1}))
    m = _fresh_metrics()
    m.update_dynamic()
    # active: (5-2)+(8-1)=10 ; total: 5+8=13
    assert m.registry.get_sample_value("iigp_db_pool_connections_active") == 10.0
    assert m.registry.get_sample_value("iigp_db_pool_connections_total") == 13.0


@pytest.mark.unit
def test_no_pool_no_broker_zero(monkeypatch):
    monkeypatch.delenv("CELERY_BROKER_URL", raising=False)
    m = _fresh_metrics()
    m.update_dynamic()
    assert m.registry.get_sample_value("iigp_db_pool_connections_active") == 0.0
    assert m.registry.get_sample_value("iigp_db_pool_connections_total") == 0.0
    assert m.registry.get_sample_value("iigp_celery_queue_length") == 0.0


@pytest.mark.unit
def test_queue_length_from_redis(monkeypatch):
    monkeypatch.setenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
    monkeypatch.setitem(sys.modules, "redis", _fake_redis_module(llen_value=5))
    m = _fresh_metrics()
    m.update_dynamic()
    assert m.registry.get_sample_value("iigp_celery_queue_length") == 5.0


@pytest.mark.unit
def test_queue_length_zero_without_broker(monkeypatch):
    monkeypatch.delenv("CELERY_BROKER_URL", raising=False)
    assert metrics_mod._collect_queue_length() == 0.0


@pytest.mark.unit
def test_update_dynamic_survives_redis_failure(monkeypatch):
    """A broker connection error must not raise; queue gauge stays 0."""
    monkeypatch.setenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
    monkeypatch.setitem(sys.modules, "redis", _fake_redis_module(raise_exc=ConnectionError("down")))
    m = _fresh_metrics()
    m.update_dynamic()  # must not raise
    assert m.registry.get_sample_value("iigp_celery_queue_length") == 0.0


@pytest.mark.unit
def test_update_dynamic_survives_pool_failure(monkeypatch):
    """A pool that raises in pop_stats is skipped, not fatal."""

    class _BadPool:
        def pop_stats(self):
            raise RuntimeError("pool exploded")

    metrics_mod.register_db_pool(_BadPool())
    m = _fresh_metrics()
    m.update_dynamic()  # must not raise
    assert m.registry.get_sample_value("iigp_db_pool_connections_active") == 0.0


@pytest.mark.unit
def test_render_latest_returns_bytes_and_triggers_update(monkeypatch):
    """Module render_latest invokes update_dynamic and always returns bytes."""
    called = {}
    monkeypatch.setattr(
        metrics_mod.METRICS, "update_dynamic", lambda: called.__setitem__("hit", True)
    )
    body, content_type = metrics_mod.render_latest()
    assert called.get("hit") is True
    assert isinstance(body, bytes)
    assert isinstance(content_type, str)
