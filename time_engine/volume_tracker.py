"""Volume tracking bridge for Layer 4 (Time Series & Trend).

Connects collected raw articles to the existing :class:`TrendDetector` so that
``velocity`` / ``acceleration`` / trend ``state`` are *computed from real
mention-volume history* instead of being guessed by the LLM.

Flow
----
1. :func:`count_term_volumes` counts how many collected articles mention each
   tracked term (case-insensitive substring; works for Korean + English).
2. :func:`record_snapshot` persists one volume point per term to the
   ``term_volume`` time-series (via :mod:`database.db_store`).
3. :func:`analyze_tracked` loads each term's series and runs ``TrendDetector``
   to produce velocity/acceleration/state, formatted for the dashboard.

Pure-Python + injectable ``store``/``detector`` so it is fully unit-testable
offline without a database or network.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from time_engine.trend_detector import TrendDetector
from utils.logger import get_logger

_log = get_logger(__name__)

# Trend state -> Korean label for the dashboard.
STATE_KO: dict[str, str] = {
    "viral": "급상승",
    "rising": "상승",
    "peaking": "정점",
    "falling": "하락",
    "stable": "유지",
}


class _Store(Protocol):
    """Minimal persistence surface (satisfied by :mod:`database.db_store`)."""

    def record_term_volumes(self, counts: dict[str, int], ts: str | None = ...) -> None: ...

    def get_term_series(self, term: str, limit: int = ...) -> list[tuple[str, float]]: ...


def count_term_volumes(articles: list[dict[str, Any]], terms: list[str]) -> dict[str, int]:
    """Count, per term, how many articles mention it (case-insensitive)."""
    haystacks = [f"{a.get('title', '')} {a.get('text', '')}".lower() for a in articles]
    counts: dict[str, int] = {}
    for term in terms:
        needle = (term or "").strip().lower()
        if not needle:
            continue
        counts[term] = sum(1 for hay in haystacks if needle in hay)
    return counts


def _parse_ts(ts: str) -> datetime:
    """Parse a SQLite/ISO timestamp string into a naive datetime."""
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(ts, fmt)
            except ValueError:
                continue
        # Last resort: epoch so the point sorts first rather than crashing.
        return datetime.min


def format_velocity_label(velocity: float, window_hours: int = 24) -> str:
    """Render a relative velocity as a dashboard label, e.g. ``+35%/24h``."""
    return f"{velocity * 100:+.0f}%/{window_hours}h"


def record_snapshot(
    articles: list[dict[str, Any]],
    terms: list[str],
    *,
    store: _Store | None = None,
    ts: str | None = None,
) -> dict[str, int]:
    """Count term volumes over ``articles`` and persist one snapshot row each."""
    if store is None:
        from database import db_store as store  # lazy default

    counts = count_term_volumes(articles, terms)
    store.record_term_volumes(counts, ts)
    return counts


def analyze_tracked(
    terms: list[str],
    *,
    store: _Store | None = None,
    detector: TrendDetector | None = None,
    top: int = 50,
) -> list[dict[str, Any]]:
    """Compute velocity/acceleration/state per term from its stored series.

    Returns a list (highest current volume first) of dicts:
    ``{term, volume, velocity, velocity_label, acceleration, state, state_ko, points}``.
    Terms with no recorded history are skipped.
    """
    if store is None:
        from database import db_store as store  # lazy default
    if detector is None:
        detector = TrendDetector()

    vel_window = int(detector.config.get("velocity_window_hours", 24))
    accel_window = int(detector.config.get("acceleration_window_hours", 6))

    results: list[dict[str, Any]] = []
    for term in terms:
        raw_series = store.get_term_series(term)
        if not raw_series:
            continue
        points = [(_parse_ts(ts), float(vol)) for ts, vol in raw_series]
        velocity = detector.compute_velocity(points, vel_window)
        acceleration = detector.compute_acceleration(points, accel_window)
        state = detector.classify_state(velocity, acceleration)
        current_volume = points[-1][1]
        results.append(
            {
                "term": term,
                "volume": current_volume,
                "velocity": round(velocity, 4),
                "velocity_label": format_velocity_label(velocity, vel_window),
                "acceleration": round(acceleration, 4),
                "state": state,
                "state_ko": STATE_KO.get(state, state),
                "points": len(points),
            }
        )

    results.sort(key=lambda r: (r["volume"], r["velocity"]), reverse=True)
    _log.info("analyze_tracked_complete", extra={"terms": len(results)})
    return results[:top]
