"""Tests for ABTestManager, StatisticalTester, VariantRouter (QA-031)."""

from __future__ import annotations

import pytest

from experiments.ab_test_manager import ABTestManager
from experiments.statistical_significance import StatisticalTester
from experiments.variant_router import VariantRouter


@pytest.mark.unit
def test_create_experiment_validates_split_sum():
    mgr = ABTestManager()
    with pytest.raises(ValueError):
        mgr.create_experiment("e", ["A", "B"], [0.5, 0.4])


@pytest.mark.unit
def test_create_experiment_requires_two_variants():
    mgr = ABTestManager()
    with pytest.raises(ValueError):
        mgr.create_experiment("e", ["A"], [1.0])


@pytest.mark.unit
def test_assignment_is_deterministic():
    mgr = ABTestManager()
    eid = mgr.create_experiment("e", ["A", "B"], [0.5, 0.5])
    v1 = mgr.assign_variant(eid, "user-123")
    v2 = mgr.assign_variant(eid, "user-123")
    assert v1 == v2
    assert v1 in ("A", "B")


@pytest.mark.unit
def test_assignment_distribution_roughly_split():
    mgr = ABTestManager()
    eid = mgr.create_experiment("e", ["A", "B"], [0.5, 0.5])
    counts = {"A": 0, "B": 0}
    for i in range(2000):
        counts[mgr.assign_variant(eid, f"u{i}")] += 1
    # within a loose tolerance of 50/50
    assert abs(counts["A"] - counts["B"]) < 300


@pytest.mark.unit
def test_assign_unknown_experiment_raises():
    mgr = ABTestManager()
    with pytest.raises(KeyError):
        mgr.assign_variant("nope", "u1")


@pytest.mark.unit
def test_record_and_results_significant():
    mgr = ABTestManager()
    eid = mgr.create_experiment("e", ["A", "B"], [0.5, 0.5])
    for _ in range(30):
        mgr.record_outcome(eid, "A", 1.0)
        mgr.record_outcome(eid, "B", 5.0)
    res = mgr.get_results(eid)
    assert res["means"]["B"] > res["means"]["A"]
    assert res["significant"] is True
    assert res["winner"] == "B"


@pytest.mark.unit
def test_results_not_significant_when_equal():
    mgr = ABTestManager()
    eid = mgr.create_experiment("e", ["A", "B"], [0.5, 0.5])
    for _ in range(20):
        mgr.record_outcome(eid, "A", 3.0)
        mgr.record_outcome(eid, "B", 3.0)
    res = mgr.get_results(eid)
    assert res["significant"] is False


@pytest.mark.unit
def test_record_unknown_variant_raises():
    mgr = ABTestManager()
    eid = mgr.create_experiment("e", ["A", "B"], [0.5, 0.5])
    with pytest.raises(ValueError):
        mgr.record_outcome(eid, "C", 1.0)


@pytest.mark.unit
def test_results_three_variants_picks_max_mean():
    mgr = ABTestManager()
    eid = mgr.create_experiment("e", ["A", "B", "C"], [0.34, 0.33, 0.33])
    for _ in range(10):
        mgr.record_outcome(eid, "A", 1.0)
        mgr.record_outcome(eid, "B", 9.0)
        mgr.record_outcome(eid, "C", 5.0)
    res = mgr.get_results(eid)
    assert res["winner"] == "B"
    assert res["p_value"] is None  # significance test only runs for 2 variants


@pytest.mark.unit
def test_results_three_variants_no_outcomes_winner_none():
    mgr = ABTestManager()
    eid = mgr.create_experiment("e", ["A", "B", "C"], [0.34, 0.33, 0.33])
    res = mgr.get_results(eid)
    assert res["winner"] is None


@pytest.mark.unit
def test_get_results_unknown_experiment_raises():
    mgr = ABTestManager()
    with pytest.raises(KeyError):
        mgr.get_results("nope")


@pytest.mark.unit
def test_statistical_tester_small_sample():
    tester = StatisticalTester()
    res = tester.test([1.0], [2.0])
    assert res["significant"] is False
    assert res["p_value"] == 1.0


@pytest.mark.unit
def test_statistical_tester_clear_difference():
    tester = StatisticalTester()
    res = tester.test([1, 1, 1, 2, 1, 2, 1], [9, 10, 9, 11, 10, 9, 10])
    assert res["p_value"] < 0.05
    assert res["significant"] is True
    assert res["winner"] == "treatment"


@pytest.mark.unit
def test_required_sample_size_positive():
    tester = StatisticalTester()
    n = tester.required_sample_size(effect_size=0.5, power=0.80)
    assert n > 0
    with pytest.raises(ValueError):
        tester.required_sample_size(effect_size=0.0)


@pytest.mark.unit
def test_variant_router_wrap_and_route():
    mgr = ABTestManager()
    eid = mgr.create_experiment("e", ["A", "B"], [1.0, 0.0])  # everyone -> A
    router = VariantRouter(mgr)

    def fa():
        return "a"

    def fb():
        return "b"

    chosen = router.wrap(fa, fb, eid, "any-unit")
    assert chosen() == "a"  # split forces variant A

    router.register(eid, "A", fa)
    assert router.route(eid, "any-unit")() == "a"


@pytest.mark.unit
def test_variant_router_missing_handler_raises():
    mgr = ABTestManager()
    eid = mgr.create_experiment("e", ["A", "B"], [1.0, 0.0])
    router = VariantRouter(mgr)
    with pytest.raises(KeyError):
        router.route(eid, "unit")
