"""Unit tests for the Phase 9 business metrics (api/metrics.py).

The no-op/degradation paths run without prometheus_client; the recording
assertions are gated behind ``importorskip('prometheus_client')`` so they run in
CI and skip cleanly in minimal environments.
"""

from __future__ import annotations

import pytest

from api import metrics
from api.metrics import _Metrics


# --------------------------------------------------------------------------
# Degradation path (no prometheus_client required)
# --------------------------------------------------------------------------
@pytest.mark.unit
def test_business_recorders_are_noop_when_unavailable():
    m = _Metrics()
    assert m.available is False
    # None of these may raise even though no collectors exist.
    m.set_graph_size(10, 5)
    m.inc_content("blog", True)
    m.observe_pipeline("daily", "success", 1.2)
    m.inc_collector("naver", "success", 3)


@pytest.mark.unit
def test_snapshot_returns_zeroed_dict_when_unavailable():
    m = _Metrics()
    snap = m.snapshot()
    assert snap == {
        "graph_nodes": 0.0,
        "graph_edges": 0.0,
        "http_requests_total": 0.0,
        "http_requests_in_progress": 0.0,
        "content_generated_total": 0.0,
        "pipeline_runs_total": 0.0,
    }


@pytest.mark.unit
def test_module_helpers_do_not_raise():
    # These operate on the shared singleton; they must be safe regardless of
    # whether prometheus_client is installed.
    metrics.record_graph_size(1, 1)
    metrics.record_content_generated("blog", True)
    metrics.record_pipeline_run("daily", "success", 0.5)
    metrics.record_collector("rss", "error", 2)
    snap = metrics.metrics_snapshot()
    assert set(snap) == {
        "graph_nodes",
        "graph_edges",
        "http_requests_total",
        "http_requests_in_progress",
        "content_generated_total",
        "pipeline_runs_total",
    }


@pytest.mark.unit
def test_pipeline_buckets_sorted_and_positive():
    assert list(metrics.PIPELINE_BUCKETS) == sorted(metrics.PIPELINE_BUCKETS)
    assert all(b > 0 for b in metrics.PIPELINE_BUCKETS)


# --------------------------------------------------------------------------
# Recording path (requires prometheus_client)
# --------------------------------------------------------------------------
@pytest.mark.unit
def test_business_metrics_recorded_with_prometheus():
    pytest.importorskip("prometheus_client")
    from prometheus_client import CollectorRegistry

    m = _Metrics()
    m.setup(CollectorRegistry())
    assert m.available is True

    m.set_graph_size(12, 7)
    m.inc_content("blog", True)
    m.inc_content("youtube", False)
    m.observe_pipeline("daily", "success", 1.5)
    m.inc_collector("naver", "success", 3)

    gsv = m.registry.get_sample_value
    assert gsv("iigp_graph_nodes") == 12.0
    assert gsv("iigp_graph_edges") == 7.0
    assert gsv("iigp_content_generated_total", {"platform": "blog", "quality": "passed"}) == 1.0
    assert gsv("iigp_content_generated_total", {"platform": "youtube", "quality": "failed"}) == 1.0
    assert gsv("iigp_pipeline_runs_total", {"pipeline": "daily", "status": "success"}) == 1.0
    assert gsv("iigp_pipeline_duration_seconds_count", {"pipeline": "daily"}) == 1.0
    assert gsv("iigp_collector_documents_total", {"source": "naver", "status": "success"}) == 3.0


@pytest.mark.unit
def test_snapshot_reflects_recorded_values():
    pytest.importorskip("prometheus_client")
    from prometheus_client import CollectorRegistry

    m = _Metrics()
    m.setup(CollectorRegistry())
    m.set_graph_size(9, 4)
    m.inc_content("blog", True)
    m.observe_pipeline("realtime", "success", 0.3)

    snap = m.snapshot()
    assert snap["graph_nodes"] == 9.0
    assert snap["graph_edges"] == 4.0
    assert snap["content_generated_total"] == 1.0
    assert snap["pipeline_runs_total"] == 1.0


# --------------------------------------------------------------------------
# Pushgateway helper (Phase 9 / worker metrics)
# --------------------------------------------------------------------------
@pytest.mark.unit
def test_push_metrics_returns_false_when_unavailable(monkeypatch):
    # Force the "prometheus unavailable" branch deterministically (no network).
    monkeypatch.setattr(metrics.METRICS, "setup", lambda *a, **k: None)
    monkeypatch.setattr(metrics.METRICS, "available", False)
    assert metrics.push_metrics(job="iigp-test") is False


@pytest.mark.unit
def test_push_metrics_success_with_stubbed_gateway(monkeypatch):
    pytest.importorskip("prometheus_client")
    import prometheus_client

    metrics.METRICS.setup()
    captured: dict[str, object] = {}

    def _fake_push(gateway, job, registry, grouping_key=None):
        captured["gateway"] = gateway
        captured["job"] = job

    monkeypatch.setattr(prometheus_client, "push_to_gateway", _fake_push)
    assert metrics.push_metrics(job="iigp-worker", gateway="gw:9091") is True
    assert captured == {"gateway": "gw:9091", "job": "iigp-worker"}


@pytest.mark.unit
def test_push_metrics_swallows_gateway_errors(monkeypatch):
    pytest.importorskip("prometheus_client")
    import prometheus_client

    metrics.METRICS.setup()

    def _boom(*a, **k):
        raise ConnectionError("gateway down")

    monkeypatch.setattr(prometheus_client, "push_to_gateway", _boom)
    # Must swallow the error and return False, never raise.
    assert metrics.push_metrics(job="iigp-worker", gateway="gw:9091") is False
