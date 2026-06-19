"""Tests for WeightUpdater, MetricsCollector, AttributionScheduler (QA-025/28/29)."""

from __future__ import annotations

from datetime import datetime

import pytest

from feedback_engine.attribution_scheduler import AttributionScheduler
from feedback_engine.metrics import MetricsCollector
from feedback_engine.weight_updater import WeightUpdater


@pytest.mark.unit
def test_bounds_clamping():
    wu = WeightUpdater()
    assert wu.apply_bounds(100.0) == wu.w_max
    assert wu.apply_bounds(-5.0) == wu.w_min


@pytest.mark.unit
def test_positive_gradient_increases_weight():
    wu = WeightUpdater({"w_edge": 0.5})
    new = wu.update("w_edge", actual=1.0, expected=0.0, gradient=1.0)
    assert new > 0.5


@pytest.mark.unit
def test_negative_error_decreases_weight():
    wu = WeightUpdater({"w_edge": 0.5})
    new = wu.update("w_edge", actual=0.0, expected=1.0, gradient=1.0)
    assert new < 0.5


@pytest.mark.unit
def test_zero_error_keeps_weight():
    wu = WeightUpdater({"w_edge": 0.5})
    new = wu.update("w_edge", actual=1.0, expected=1.0, gradient=1.0)
    assert new == pytest.approx(0.5)


@pytest.mark.unit
def test_update_never_exceeds_bounds():
    wu = WeightUpdater({"w": 9.999})
    new = wu.update("w", actual=1e6, expected=0.0, gradient=1.0)
    assert wu.w_min <= new <= wu.w_max


@pytest.mark.unit
def test_metrics_record_and_latest(tmp_path):
    mc = MetricsCollector(store_dir=tmp_path)
    mc.record("c1", "blog", {"views": 100, "clicks": 5, "ctr": 0.05})
    mc.record("c1", "blog", {"views": 200, "clicks": 12, "ctr": 0.06})
    latest = mc.get_latest("c1")
    assert latest["views"] == 200
    assert len(mc.get_time_series("c1")) == 2


@pytest.mark.unit
def test_metrics_empty_series(tmp_path):
    mc = MetricsCollector(store_dir=tmp_path)
    assert mc.get_time_series("missing") == []
    assert mc.get_latest("missing") == {}


@pytest.mark.unit
def test_attribution_schedule_has_five_points():
    sched = AttributionScheduler()
    jobs = sched.schedule("c1", datetime(2026, 1, 1, 0, 0, 0))
    assert len(jobs) == 5


@pytest.mark.unit
def test_attribution_decay_correction_projects_total():
    sched = AttributionScheduler()
    sched.record_raw("c1", "72h", 75.0)
    result = sched.run_attribution("c1", checkpoint_hours=72)
    # 72h correction is 0.75 -> projected ~ 100
    assert result["projected_total"] == pytest.approx(100.0, abs=1e-6)


@pytest.mark.unit
def test_attribution_aggregate_total_uses_latest():
    sched = AttributionScheduler()
    sched.record_raw("c1", "24h", 40.0)
    sched.record_raw("c1", "7d", 95.0)
    # latest checkpoint is 7d (correction 0.95) -> ~100
    assert sched.aggregate_total("c1") == pytest.approx(100.0, abs=1e-6)
