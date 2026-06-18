"""Tests for TrendDetector velocity/acceleration/state (DD-008 / QA-011)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from time_engine.decay_model import DecayModel
from time_engine.trend_detector import TrendDetector


def _series(values, start=None, step_hours=6):
    start = start or datetime(2026, 1, 1, 0, 0, 0)
    return [(start + timedelta(hours=i * step_hours), v) for i, v in enumerate(values)]


@pytest.mark.unit
def test_velocity_positive_growth():
    td = TrendDetector()
    # value 24h ago = 100, now = 130 -> +0.30
    scores = _series([100, 110, 120, 125, 130], step_hours=6)  # spans 24h
    v = td.compute_velocity(scores, window_hours=24)
    assert v == pytest.approx(0.30, abs=1e-6)


@pytest.mark.unit
def test_velocity_zero_past_value():
    td = TrendDetector()
    scores = _series([0, 0, 0, 10])
    assert td.compute_velocity(scores) == 0.0


@pytest.mark.unit
def test_velocity_insufficient_data():
    td = TrendDetector()
    assert td.compute_velocity([(datetime(2026, 1, 1), 5.0)]) == 0.0


@pytest.mark.unit
def test_acceleration_changes_with_curvature():
    td = TrendDetector()
    accelerating = _series([10, 12, 16, 24, 40], step_hours=6)
    acc = td.compute_acceleration(accelerating, window_hours=6)
    assert acc > 0.0


@pytest.mark.unit
def test_classify_state_viral():
    td = TrendDetector()
    assert td.classify_state(velocity=1.5, acceleration=0.1) == "viral"


@pytest.mark.unit
def test_classify_state_rising():
    td = TrendDetector()
    assert td.classify_state(velocity=0.30, acceleration=0.10) == "rising"


@pytest.mark.unit
def test_classify_state_falling():
    td = TrendDetector()
    assert td.classify_state(velocity=-0.20, acceleration=-0.05) == "falling"


@pytest.mark.unit
def test_classify_state_peaking():
    td = TrendDetector()
    assert td.classify_state(velocity=0.01, acceleration=0.0) == "peaking"


@pytest.mark.unit
def test_optimal_publish_window():
    td = TrendDetector()
    assert td.is_optimal_publish_window(velocity=0.30, acceleration=0.10) is True
    # rising but acceleration too low
    assert td.is_optimal_publish_window(velocity=0.30, acceleration=0.01) is False


@pytest.mark.unit
def test_decay_half_life():
    dm = DecayModel()
    created = datetime(2026, 1, 1)
    # exactly 7 days later -> decay ~ 0.5 (default half-life 7d)
    now = created + timedelta(days=7)
    assert dm.compute_decay(created, "default", now=now) == pytest.approx(0.5, abs=1e-3)


@pytest.mark.unit
def test_decay_monotonic_decrease():
    dm = DecayModel()
    created = datetime(2026, 1, 1)
    d1 = dm.compute_decay(created, now=created + timedelta(days=1))
    d2 = dm.compute_decay(created, now=created + timedelta(days=10))
    assert 0 < d2 < d1 <= 1.0
