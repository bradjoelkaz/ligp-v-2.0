"""Unit tests for the L7 feedback loop (feedback_engine/feedback_loop.py)."""

from __future__ import annotations

import pytest

from feedback_engine import feedback_loop as fl


class FakeStore:
    """In-memory stand-in for database.db_store."""

    def __init__(self, records=None, weights=None):
        self.records = records or []
        self._weights = weights or {}
        self.saved = None

    def record_content_feedback(
        self, content_id, platform, expected_score, actual_score, features=None, metrics=None
    ):
        self.records.append(
            {
                "content_id": content_id,
                "platform": platform,
                "expected_score": expected_score,
                "actual_score": actual_score,
                "features": features or {},
            }
        )

    def get_recent_feedback(self, limit=200):
        return self.records

    def save_weights(self, weights):
        self.saved = dict(weights)
        self._weights = dict(weights)

    def load_weights(self):
        return dict(self._weights)


# --- derive_actual_score ---------------------------------------------------


def test_derive_actual_score_high():
    assert fl.derive_actual_score({"views": 1000, "clicks": 50, "revenue": 5.0}) == pytest.approx(
        1.0
    )


def test_derive_actual_score_low():
    score = fl.derive_actual_score({"views": 1000, "clicks": 5, "revenue": 0.5})
    assert 0.0 < score < 0.3


def test_derive_actual_score_explicit_passthrough():
    assert fl.derive_actual_score({"actual_score": 0.42}) == 0.42


def test_derive_actual_score_zero_views():
    assert fl.derive_actual_score({"views": 0, "clicks": 0, "revenue": 0}) == 0.0


# --- load_calibrated_weights -----------------------------------------------


def test_load_calibrated_weights_defaults():
    assert fl.load_calibrated_weights(store=FakeStore()) == fl.DEFAULT_OPPORTUNITY_WEIGHTS


def test_load_calibrated_weights_merges_persisted():
    store = FakeStore(weights={"w_trend": 0.99})
    merged = fl.load_calibrated_weights(store=store)
    assert merged["w_trend"] == 0.99
    assert merged["w_revenue"] == fl.DEFAULT_OPPORTUNITY_WEIGHTS["w_revenue"]


# --- record_performance ----------------------------------------------------


def test_record_performance_persists_and_returns_actual():
    store = FakeStore()
    actual = fl.record_performance(
        "c1",
        "blog",
        0.3,
        {"views": 1000, "clicks": 50, "revenue": 5.0},
        features={"w_trend": 1.0},
        store=store,
    )
    assert actual == pytest.approx(1.0)
    assert store.records[0]["content_id"] == "c1"


# --- calibrate -------------------------------------------------------------


def test_calibrate_empty_returns_zero():
    summary = fl.calibrate(store=FakeStore())
    assert summary["samples"] == 0
    assert summary["mean_abs_error"] == 0.0


def test_calibrate_raises_underpredicted_weight():
    records = [
        {"expected_score": 0.2, "actual_score": 1.0, "features": {"w_trend": 1.0, "w_risk": 0.0}}
        for _ in range(5)
    ]
    store = FakeStore(records=records)
    summary = fl.calibrate(store=store)
    assert summary["samples"] == 5
    # under-prediction with positive feature -> weight increases
    assert summary["updated_weights"]["w_trend"] > fl.DEFAULT_OPPORTUNITY_WEIGHTS["w_trend"]
    # zero-gradient feature stays unchanged
    assert summary["updated_weights"]["w_risk"] == pytest.approx(
        fl.DEFAULT_OPPORTUNITY_WEIGHTS["w_risk"]
    )
    assert summary["mean_abs_error"] == pytest.approx(0.8)
    assert store.saved is not None  # weights persisted


# --- default-store integration (covers lazy db_store import path) ----------


def test_default_store_integration(tmp_path, monkeypatch):
    from database import db_store

    monkeypatch.setattr(db_store, "DB_PATH", str(tmp_path / "fb.db"))
    db_store.init_db()

    fl.record_performance(
        "c1",
        "blog",
        0.2,
        {"views": 1000, "clicks": 60, "revenue": 6.0},
        features={"w_trend": 1.0},
    )
    summary = fl.calibrate()
    assert summary["samples"] == 1
    # reload persisted weights via default store
    reloaded = fl.load_calibrated_weights()
    assert reloaded["w_trend"] == summary["updated_weights"]["w_trend"]
