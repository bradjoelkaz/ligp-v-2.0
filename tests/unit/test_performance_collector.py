"""Tests for the L7 performance collector (feedback_engine/performance_collector.py)."""

from __future__ import annotations

import pytest

from feedback_engine import performance_collector as pc


class FakeStore:
    def __init__(self):
        self.records = []
        self.weights = {}
        self.saved = None
        self.snapshots = []

    def record_content_feedback(
        self, content_id, platform, expected, actual, features=None, metrics=None
    ):
        self.records.append(
            {"expected_score": expected, "actual_score": actual, "features": features or {}}
        )

    def get_recent_feedback(self, limit=200):
        return self.records

    def save_weights(self, weights):
        self.saved = dict(weights)
        self.weights = dict(weights)

    def load_weights(self):
        return dict(self.weights)

    def record_weights_snapshot(self, weights):
        self.snapshots.append(dict(weights))


def test_simulate_metrics_deterministic():
    a = pc.simulate_metrics("abc")
    b = pc.simulate_metrics("abc")
    assert a == b
    assert a["views"] > 0 and "clicks" in a and "revenue" in a


def test_collect_performance_persists_and_returns(monkeypatch):
    store = FakeStore()
    res = pc.collect_performance(
        "c1",
        "blog",
        0.3,
        features={"w_trend": 1.0},
        fetcher=lambda cid: {"views": 1000, "clicks": 50, "revenue": 5.0},
        store=store,
    )
    assert res["actual_score"] == pytest.approx(1.0)
    assert store.records and store.records[0]["expected_score"] == 0.3


def test_collect_performance_fetch_failure_is_safe():
    store = FakeStore()

    def boom(cid):
        raise RuntimeError("api down")

    res = pc.collect_performance("c2", "blog", 0.2, fetcher=boom, store=store)
    assert res["metrics"]["views"] == 0
    assert res["actual_score"] == 0.0  # zero metrics -> zero score


def test_collect_and_calibrate_updates_and_snapshots():
    store = FakeStore()
    items = [
        {
            "content_id": f"c{i}",
            "platform": "blog",
            "expected_score": 0.1,
            "features": {"w_trend": 1.0, "w_risk": 0.0},
        }
        for i in range(3)
    ]
    summary = pc.collect_and_calibrate(
        items, fetcher=lambda cid: {"views": 1000, "clicks": 60, "revenue": 6.0}, store=store
    )
    assert summary["samples"] == 3
    # under-predicted (expected 0.1, actual high) with positive trend feature -> weight up
    assert summary["updated_weights"]["w_trend"] > 0.30
    assert store.saved is not None
    assert store.snapshots  # weight history snapshot recorded


def test_collect_and_calibrate_default_store(tmp_path, monkeypatch):
    from database import db_store

    monkeypatch.setattr(db_store, "DB_PATH", str(tmp_path / "p.db"))
    db_store.init_db()
    summary = pc.collect_and_calibrate(
        [
            {
                "content_id": "x",
                "platform": "blog",
                "expected_score": 0.2,
                "features": {"w_trend": 1.0},
            }
        ]
    )
    assert summary["samples"] == 1
    assert db_store.get_weights_history()  # snapshot persisted via default store
