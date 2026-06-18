"""Tests for ThompsonSelector, Ranker and MarkowitzOptimizer (QA-019/020)."""

from __future__ import annotations

import random

import pytest

from decision_engine.optimizer import MarkowitzOptimizer
from decision_engine.selector import ThompsonSelector
from scoring_engine.ranking import Ranker


def _cands(n, topic_prefix="t"):
    return [
        {
            "node_id": f"n{i}",
            "topic": f"{topic_prefix}{i % 3}",
            "final_score": 1.0 - i * 0.01,
            "success": 5,
            "fail": 5,
        }
        for i in range(n)
    ]


@pytest.mark.unit
def test_select_returns_non_empty():
    sel = ThompsonSelector(rng=random.Random(1))
    out = sel.select(_cands(10), platform="blog", n=5)
    assert 1 <= len(out) <= 5


@pytest.mark.unit
def test_select_empty_when_n_zero():
    sel = ThompsonSelector(rng=random.Random(1))
    assert sel.select(_cands(10), platform="blog", n=0) == []


@pytest.mark.unit
def test_enforce_diversity_limits_per_topic():
    sel = ThompsonSelector(rng=random.Random(1))
    cands = [{"node_id": f"n{i}", "topic": "same"} for i in range(10)]
    out = sel.enforce_diversity(cands, max_same_topic=2)
    assert len(out) == 2


@pytest.mark.unit
def test_apply_quota_truncates():
    sel = ThompsonSelector(rng=random.Random(1))
    cands = [{"node_id": f"n{i}", "topic": f"t{i}"} for i in range(500)]
    # instagram quota is 200 in platforms.yaml
    out = sel.apply_quota(cands, "instagram")
    assert len(out) <= 200


@pytest.mark.unit
def test_ranker_blends_and_sorts():
    ranker = Ranker()
    candidates = [
        {"node_id": "a", "score": 0.9, "revenue_score": 10, "probability_score": 0.1},
        {"node_id": "b", "score": 0.4, "revenue_score": 50, "probability_score": 0.9},
        {"node_id": "c", "score": 0.6, "revenue_score": 30, "probability_score": 0.5},
    ]
    out = ranker.rank(candidates)
    finals = [c["final_score"] for c in out]
    assert finals == sorted(finals, reverse=True)


@pytest.mark.unit
def test_ranker_filters_below_threshold():
    ranker = Ranker(min_graph_score=0.35)
    candidates = [{"node_id": "a", "score": 0.5}, {"node_id": "b", "score": 0.2}]
    kept = ranker.filter_below_threshold(candidates)
    assert [c["node_id"] for c in kept] == ["a"]


@pytest.mark.unit
def test_ranker_top_k():
    ranker = Ranker()
    ranked = [{"node_id": str(i)} for i in range(10)]
    assert len(ranker.top_k(ranked, 3)) == 3


@pytest.mark.unit
def test_markowitz_weights_sum_to_one():
    opt = MarkowitzOptimizer()
    returns = [0.1, 0.2, 0.15]
    cov = [[0.04, 0.0, 0.0], [0.0, 0.09, 0.0], [0.0, 0.0, 0.06]]
    w = opt.optimize([{}, {}, {}], returns, cov)
    assert pytest.approx(sum(w), abs=1e-6) == 1.0
    assert all(x >= opt.w_min - 1e-9 for x in w)


@pytest.mark.unit
def test_markowitz_single_candidate():
    opt = MarkowitzOptimizer()
    assert opt.optimize([{}], [0.1], [[0.04]]) == [1.0]


@pytest.mark.unit
def test_markowitz_validates_alignment():
    opt = MarkowitzOptimizer()
    with pytest.raises(ValueError):
        opt.optimize([{}, {}], [0.1], [[0.04]])
