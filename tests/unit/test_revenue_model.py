"""Tests for RevenueModel and ProbabilityModel (DD-002 / QA-014/015)."""

from __future__ import annotations

import random

import pytest

from scoring_engine.probability_model import ProbabilityModel
from scoring_engine.revenue_model import RevenueModel


@pytest.mark.unit
def test_stream_weights_sum_to_one():
    rm = RevenueModel()
    assert pytest.approx(sum(rm.stream_weights.values()), abs=1e-9) == 1.0


@pytest.mark.unit
def test_emotion_boost_within_bounds():
    rm = RevenueModel()
    for emotion in ["joy", "fear", "anger", "surprise", "sadness", "neutral", "unknown"]:
        boost = rm.compute_emotion_boost(emotion)
        assert 0.5 <= boost <= 3.0


@pytest.mark.unit
def test_risk_penalty_within_unit_interval():
    rm = RevenueModel()
    assert rm.compute_risk_penalty([]) == 0.0
    full = rm.compute_risk_penalty(["copyright_risk", "controversy_risk", "saturation_risk"])
    assert full == pytest.approx(1.0, abs=1e-9)
    assert 0.0 <= rm.compute_risk_penalty(["copyright_risk"]) <= 1.0


@pytest.mark.unit
def test_estimate_cpm_uses_seed():
    rm = RevenueModel()
    # blog seed CPM is 4.5 in config/cpm_history.seed.json
    assert rm.estimate_cpm("blog") == pytest.approx(4.5)
    # unknown platform falls back to 1.0
    assert rm.estimate_cpm("unknown_platform") == pytest.approx(1.0)


@pytest.mark.unit
def test_compute_decreases_with_risk():
    rm = RevenueModel()
    clean = rm.compute("n1", "youtube", "surprise", [])
    risky = rm.compute("n1", "youtube", "surprise", ["copyright_risk"])
    assert clean > risky > 0


@pytest.mark.unit
def test_probability_update_increases_alpha():
    pm = ProbabilityModel(rng=random.Random(42))
    mean_before, _ = pm.get_ctr_estimate("blog")
    pm.update_ctr("blog", clicks=50, impressions=100)
    mean_after, _ = pm.get_ctr_estimate("blog")
    assert mean_after > mean_before


@pytest.mark.unit
def test_probability_update_validates_inputs():
    pm = ProbabilityModel()
    with pytest.raises(ValueError):
        pm.update_ctr("blog", clicks=10, impressions=5)


@pytest.mark.unit
def test_sample_ctr_in_unit_interval():
    pm = ProbabilityModel(rng=random.Random(7))
    for _ in range(100):
        assert 0.0 <= pm.sample_ctr("youtube") <= 1.0


@pytest.mark.unit
def test_ctr_estimate_mean_and_variance_ranges():
    pm = ProbabilityModel()
    mean, var = pm.get_ctr_estimate("blog")
    assert 0.0 < mean < 1.0
    assert var > 0.0
