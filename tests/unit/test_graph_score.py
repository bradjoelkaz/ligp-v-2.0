"""Tests for GraphScoreComputer (QA-017 / DD-002)."""

from __future__ import annotations

import pytest

from scoring_engine.graph_score import GraphScoreComputer


@pytest.mark.unit
def test_weights_sum_to_one():
    gsc = GraphScoreComputer()
    total = (
        gsc.w.get("w_edge", 0)
        + gsc.w.get("w_centrality", 0)
        + gsc.w.get("w_trend", 0)
        + gsc.w.get("w_event", 0)
    )
    assert pytest.approx(total, abs=1e-9) == 1.0


@pytest.mark.unit
def test_normalize_minmax_range():
    gsc = GraphScoreComputer()
    out = gsc.normalize_minmax([10.0, 20.0, 30.0])
    assert out == [0.0, 0.5, 1.0]
    assert all(0.0 <= v <= 1.0 for v in out)


@pytest.mark.unit
def test_normalize_minmax_constant_returns_zeros():
    gsc = GraphScoreComputer()
    assert gsc.normalize_minmax([5.0, 5.0, 5.0]) == [0.0, 0.0, 0.0]


@pytest.mark.unit
def test_compute_all_zero_inputs_is_zero():
    gsc = GraphScoreComputer()
    assert gsc.compute("n", 0.0, 0.0, 0.0, 0.0) == 0.0


@pytest.mark.unit
def test_compute_all_one_inputs_equals_weight_sum():
    gsc = GraphScoreComputer()
    # with all normalized components = 1, score == sum of weights == 1.0
    assert gsc.compute("n", 1.0, 1.0, 1.0, 1.0) == pytest.approx(1.0, abs=1e-9)


@pytest.mark.unit
def test_batch_compute_sorted_descending():
    gsc = GraphScoreComputer()
    candidates = [
        {"node_id": "a", "edge_sum": 1, "centrality": 1, "trend_score": 1, "event_boost": 1},
        {"node_id": "b", "edge_sum": 0, "centrality": 0, "trend_score": 0, "event_boost": 0},
        {
            "node_id": "c",
            "edge_sum": 0.5,
            "centrality": 0.5,
            "trend_score": 0.5,
            "event_boost": 0.5,
        },
    ]
    out = gsc.batch_compute(candidates)
    scores = [c["score"] for c in out]
    assert scores == sorted(scores, reverse=True)
    assert out[0]["node_id"] == "a"
    assert out[-1]["node_id"] == "b"


@pytest.mark.unit
def test_batch_compute_empty():
    assert GraphScoreComputer().batch_compute([]) == []
