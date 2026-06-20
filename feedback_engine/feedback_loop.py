"""L7 feedback loop: self-calibrate opportunity-score weights from performance.

Closes the blueprint's Layer-7 loop. Performance feedback for published content
is persisted (SQLite ``content_feedback``), then the opportunity-score weights
are nudged toward reality with the existing online update rule in
:class:`feedback_engine.weight_updater.WeightUpdater`:

    w_new = clip(w_old + lr * (actual - expected) * feature, [w_min, w_max])

Each feedback record carries the per-component feature values used at selection
time (``features``), the predicted ``expected_score`` and the realised
``actual_score``. Calibrated weights are saved to ``weights_state`` and reloaded
on the next pipeline run via :func:`load_calibrated_weights`.

Pure-Python with an injectable ``store`` so it is unit-testable offline.
"""

from __future__ import annotations

from typing import Any, Protocol

from feedback_engine.weight_updater import WeightUpdater
from utils.logger import get_logger

_log = get_logger(__name__)

# Default opportunity-score weights (blueprint L5): trend, revenue, SEO, risk.
DEFAULT_OPPORTUNITY_WEIGHTS: dict[str, float] = {
    "w_trend": 0.30,
    "w_revenue": 0.35,
    "w_seo": 0.20,
    "w_risk": 0.15,
}


class _Store(Protocol):
    def record_content_feedback(
        self,
        content_id: str,
        platform: str,
        expected_score: float,
        actual_score: float,
        features: dict[str, float] | None = ...,
        metrics: dict[str, Any] | None = ...,
    ) -> None: ...

    def get_recent_feedback(self, limit: int = ...) -> list[dict[str, Any]]: ...

    def save_weights(self, weights: dict[str, float]) -> None: ...

    def load_weights(self) -> dict[str, float]: ...


def _store() -> Any:
    from database import db_store

    return db_store


def load_calibrated_weights(store: _Store | None = None) -> dict[str, float]:
    """Return persisted calibrated weights merged over the defaults."""
    store = store or _store()
    merged = dict(DEFAULT_OPPORTUNITY_WEIGHTS)
    merged.update(store.load_weights())
    return merged


def record_performance(
    content_id: str,
    platform: str,
    expected_score: float,
    metrics: dict[str, Any],
    *,
    features: dict[str, float] | None = None,
    store: _Store | None = None,
) -> float:
    """Persist a performance record; returns the derived ``actual_score`` [0,1].

    ``actual_score`` is a normalized blend of realised CTR and revenue so it is
    directly comparable to the predicted opportunity score.
    """
    store = store or _store()
    actual_score = derive_actual_score(metrics)
    store.record_content_feedback(
        content_id, platform, expected_score, actual_score, features, metrics
    )
    return actual_score


def derive_actual_score(metrics: dict[str, Any]) -> float:
    """Map raw performance metrics to a normalized [0,1] score.

    Blends CTR (vs a 5% reference) and revenue-per-1k-views (vs a $5 reference),
    each clamped to [0,1]. Falls back to an explicit ``actual_score`` if given.
    """
    if "actual_score" in metrics:
        return _clamp01(float(metrics["actual_score"]))

    views = float(metrics.get("views", 0) or 0)
    clicks = float(metrics.get("clicks", 0) or 0)
    revenue = float(metrics.get("revenue", 0.0) or 0.0)

    ctr = (clicks / views) if views > 0 else 0.0
    ctr_score = _clamp01(ctr / 0.05)  # 5% CTR -> 1.0
    rpm = (revenue / views * 1000.0) if views > 0 else 0.0
    rev_score = _clamp01(rpm / 5.0)  # $5 RPM -> 1.0
    return round(0.5 * ctr_score + 0.5 * rev_score, 4)


def calibrate(
    *,
    limit: int = 200,
    store: _Store | None = None,
    updater: WeightUpdater | None = None,
) -> dict[str, Any]:
    """Run one calibration pass over recent feedback and persist new weights.

    For each feedback record, every opportunity-score component is nudged by the
    prediction error scaled by that component's feature value. Returns a summary
    with the updated weights, sample count and mean absolute error.
    """
    store = store or _store()
    records = store.get_recent_feedback(limit)
    weights = load_calibrated_weights(store)

    if not records:
        return {"updated_weights": weights, "samples": 0, "mean_abs_error": 0.0}

    updater = updater or WeightUpdater(weights)
    # Ensure the updater starts from the merged weights even if a custom one passed.
    for comp, val in weights.items():
        updater.weights.setdefault(comp, val)

    total_abs_error = 0.0
    for rec in records:
        expected = float(rec.get("expected_score", 0.0) or 0.0)
        actual = float(rec.get("actual_score", 0.0) or 0.0)
        total_abs_error += abs(actual - expected)
        features = rec.get("features") or {}
        for comp in weights:
            gradient = float(features.get(comp, 0.0) or 0.0)
            if gradient:
                updater.update(comp, actual, expected, gradient=gradient)

    store.save_weights(updater.weights)
    # Record a snapshot for the OS dashboard weight-trend chart (best-effort).
    snapshot = getattr(store, "record_weights_snapshot", None)
    if callable(snapshot):
        snapshot(dict(updater.weights))
    summary = {
        "updated_weights": dict(updater.weights),
        "samples": len(records),
        "mean_abs_error": round(total_abs_error / len(records), 4),
    }
    _log.info("feedback_calibration_complete", extra=summary)
    return summary


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))
