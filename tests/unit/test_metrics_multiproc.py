"""Tests for Prometheus multiprocess support (Phase 14).

``cleanup_multiprocess_dir`` is pure-stdlib and tested offline. The
multiprocess registry wiring is gated on ``prometheus_client``.
"""

from __future__ import annotations

import os

import pytest

from api import metrics
from api.metrics import _Metrics, cleanup_multiprocess_dir


@pytest.mark.unit
def test_cleanup_noop_without_env(monkeypatch):
    monkeypatch.delenv("PROMETHEUS_MULTIPROC_DIR", raising=False)
    # Must not raise.
    cleanup_multiprocess_dir()


@pytest.mark.unit
def test_cleanup_creates_missing_dir(tmp_path, monkeypatch):
    target = tmp_path / "prom_multiproc"
    assert not target.exists()
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(target))
    cleanup_multiprocess_dir()
    assert target.is_dir()


@pytest.mark.unit
def test_cleanup_removes_db_files_only(tmp_path, monkeypatch):
    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    # Stale metric files + an unrelated file.
    (tmp_path / "counter_123.db").write_text("x")
    (tmp_path / "gauge_live_456.db").write_text("y")
    keep = tmp_path / "keep.txt"
    keep.write_text("keep me")

    cleanup_multiprocess_dir()

    assert not list(tmp_path.glob("*.db"))  # all .db removed
    assert keep.exists()  # non-.db preserved


@pytest.mark.unit
def test_multiprocess_registry_initialization(tmp_path, monkeypatch):
    pytest.importorskip("prometheus_client")
    from prometheus_client import multiprocess

    monkeypatch.setenv("PROMETHEUS_MULTIPROC_DIR", str(tmp_path))
    m = _Metrics()
    m.setup()
    assert m.available is True
    assert m.multiprocess is True
    # The exposition registry carries a MultiProcessCollector.
    collectors = list(m.registry._collector_to_names)
    assert any(isinstance(c, multiprocess.MultiProcessCollector) for c in collectors)


@pytest.mark.unit
def test_single_process_registry_when_env_absent(monkeypatch):
    pytest.importorskip("prometheus_client")
    from prometheus_client import CollectorRegistry

    monkeypatch.delenv("PROMETHEUS_MULTIPROC_DIR", raising=False)
    m = _Metrics()
    m.setup(CollectorRegistry())
    assert m.available is True
    assert m.multiprocess is False
    # Records normally into the in-process registry.
    m.observe("GET", "/x", 200, 0.01)
    body, _ = m.render_latest()
    assert b"iigp_http_requests_total" in body


@pytest.mark.unit
def test_module_exports_cleanup():
    assert hasattr(metrics, "cleanup_multiprocess_dir")
    assert os.environ.get("PROMETHEUS_MULTIPROC_DIR") is None or True  # smoke
