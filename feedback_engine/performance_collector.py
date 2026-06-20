"""Performance collection for the L7 feedback loop (Phase 7).

Fetches (or, offline, deterministically simulates) the real market reaction to a
deployed content item \u2014 views, CTR, subscribers, ad revenue \u2014 and feeds it into
the SQLite ``content_feedback`` table via :func:`feedback_loop.record_performance`.
Running :func:`feedback_loop.calibrate` afterwards nudges the opportunity-score
weights toward reality so the next topic-selection run reflects actual results.

``simulate_metrics`` is deterministic per ``content_id`` so tests and offline
runs are reproducible.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

from feedback_engine import feedback_loop
from utils.logger import get_logger

_log = get_logger(__name__)


def simulate_metrics(content_id: str) -> dict[str, Any]:
    """Deterministic pseudo-metrics derived from ``content_id`` (offline mode)."""
    digest = hashlib.sha256(content_id.encode("utf-8")).digest()
    views = 500 + digest[0] * 50  # 500..13_250
    clicks = int(views * (0.02 + (digest[1] % 50) / 1000.0))  # 2%..7% CTR
    subscribers = digest[2] % 40
    revenue = round(views / 1000.0 * (1.0 + (digest[3] % 400) / 100.0), 2)  # RPM $1..$5
    return {
        "views": views,
        "clicks": clicks,
        "subscribers": subscribers,
        "revenue": revenue,
    }


def collect_performance(
    content_id: str,
    platform: str,
    expected_score: float,
    *,
    features: dict[str, float] | None = None,
    fetcher: Callable[[str], dict[str, Any]] | None = None,
    store: Any | None = None,
) -> dict[str, Any]:
    """Fetch performance for one item and persist it as L7 feedback.

    ``fetcher`` lets callers supply real metrics; it defaults to
    :func:`simulate_metrics`. Returns ``{metrics, actual_score}``.
    """
    fetch = fetcher or simulate_metrics
    try:
        metrics = fetch(content_id)
    except Exception as exc:  # noqa: BLE001 - never crash on a flaky fetch
        _log.warning(
            "performance_fetch_failed", extra={"content_id": content_id, "error": str(exc)}
        )
        metrics = {"views": 0, "clicks": 0, "subscribers": 0, "revenue": 0.0}

    actual = feedback_loop.record_performance(
        content_id, platform, expected_score, metrics, features=features, store=store
    )
    _log.info("collected_performance", extra={"content_id": content_id, "actual": actual})
    return {"metrics": metrics, "actual_score": actual}


def collect_and_calibrate(
    items: list[dict[str, Any]],
    *,
    fetcher: Callable[[str], dict[str, Any]] | None = None,
    store: Any | None = None,
) -> dict[str, Any]:
    """Collect performance for many items, then run one calibration pass.

    Each item: ``{content_id, platform, expected_score, features?}``. Returns the
    calibration summary (updated weights, samples, mean error).
    """
    for item in items:
        collect_performance(
            item["content_id"],
            item.get("platform", "unknown"),
            float(item.get("expected_score", 0.0)),
            features=item.get("features"),
            fetcher=fetcher,
            store=store,
        )
    return feedback_loop.calibrate(store=store)
