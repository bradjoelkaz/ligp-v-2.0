"""Supplementary tests closing coverage gaps in the scoped core packages.

These exercise less-obvious branches (empty inputs, fallbacks, edge cases) so
the coverage-gated packages stay above the 90% threshold.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from decision_engine.selector import ThompsonSelector
from feedback_engine.attribution_scheduler import AttributionScheduler
from scoring_engine.probability_model import ProbabilityModel
from scoring_engine.ranking import Ranker
from scoring_engine.revenue_model import RevenueModel
from time_engine.decay_model import DecayModel


@pytest.mark.unit
def test_revenue_batch_compute_annotates():
    rm = RevenueModel()
    items = [
        {"node_id": "a", "platform": "blog", "emotion": "joy", "risk_flags": []},
        {
            "node_id": "b",
            "platform": "youtube",
            "emotion": "fear",
            "risk_flags": ["copyright_risk"],
        },
    ]
    out = rm.batch_compute(items)
    assert all("revenue_score" in i for i in out)
    assert out[0]["revenue_score"] >= 0


@pytest.mark.unit
def test_ranking_empty_inputs():
    ranker = Ranker()
    assert ranker.rank([]) == []
    assert ranker.filter_below_threshold([]) == []
    assert ranker.top_k([], 5) == []


@pytest.mark.unit
def test_ranking_top_k_negative():
    ranker = Ranker()
    assert ranker.top_k([{"a": 1}], -3) == []


@pytest.mark.unit
def test_probability_unknown_platform_uses_default_prior():
    pm = ProbabilityModel()
    mean, var = pm.get_ctr_estimate("brand_new_platform")
    assert 0.0 < mean < 1.0 and var > 0.0
    assert 0.0 <= pm.sample_ctr("brand_new_platform") <= 1.0


@pytest.mark.unit
def test_decay_apply_to_score():
    dm = DecayModel()
    created = datetime(2026, 1, 1)
    decayed = dm.apply_decay_to_score(100.0, created, "default", now=created + timedelta(days=7))
    assert decayed == pytest.approx(50.0, abs=0.1)


@pytest.mark.unit
def test_selector_quota_none_for_unknown_platform():
    sel = ThompsonSelector()
    cands = [{"node_id": f"n{i}", "topic": f"t{i}"} for i in range(10)]
    # unknown platform -> no configured quota -> list returned unchanged
    assert len(sel.apply_quota(cands, "no_such_platform")) == 10


@pytest.mark.unit
def test_attribution_aggregate_empty_is_zero():
    sched = AttributionScheduler()
    assert sched.aggregate_total("never-seen") == 0.0


@pytest.mark.unit
def test_attribution_point_for_hours_invalid():
    sched = AttributionScheduler()
    with pytest.raises(ValueError):
        sched.run_attribution("c1", checkpoint_hours=999)


@pytest.mark.unit
def test_attribution_invalid_checkpoint_label():
    sched = AttributionScheduler()
    sched.points = ["bogus"]
    with pytest.raises(ValueError):
        sched.schedule("c1", datetime(2026, 1, 1))
