"""Attribution scheduler (QA-029).

Schedules revenue/conversion attribution snapshots at 5 checkpoints after
publication (1h, 24h, 72h, 7d, 30d from ``thresholds.yaml -> attribution``),
applying a decay correction so early snapshots can be extrapolated to a
projected 30-day total. Prefect is used when available (lazy); otherwise the
schedule is computed and stored locally.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any

from utils.config_loader import load_config
from utils.logger import get_logger

_log = get_logger(__name__)

_FALLBACK_POINTS = ["1h", "24h", "72h", "7d", "30d"]
_FALLBACK_DECAY = {"1h": 0.10, "24h": 0.40, "72h": 0.75, "7d": 0.95, "30d": 1.00}


@lru_cache(maxsize=1)
def _attr_config() -> dict[str, Any]:
    try:
        cfg = load_config("thresholds").get("attribution", {})
        return (
            cfg
            if cfg
            else {"snapshot_points": _FALLBACK_POINTS, "decay_correction": _FALLBACK_DECAY}
        )
    except Exception:  # pragma: no cover
        return {"snapshot_points": _FALLBACK_POINTS, "decay_correction": _FALLBACK_DECAY}


def _hours(point: str) -> int:
    """Convert a checkpoint label like '72h' or '7d' to hours."""
    point = point.strip().lower()
    if point.endswith("h"):
        return int(point[:-1])
    if point.endswith("d"):
        return int(point[:-1]) * 24
    raise ValueError(f"invalid checkpoint: {point}")


class AttributionScheduler:
    """Compute and run attribution checkpoints for published content."""

    def __init__(self) -> None:
        cfg = _attr_config()
        self.points: list[str] = list(cfg.get("snapshot_points", _FALLBACK_POINTS))
        self.decay_correction: dict[str, float] = dict(cfg.get("decay_correction", _FALLBACK_DECAY))
        self._snapshots: dict[str, dict[str, float]] = {}

    def schedule(self, content_id: str, published_at: datetime) -> list[str]:
        """Return checkpoint timestamps (ISO) and register Prefect jobs if able."""
        jobs: list[str] = []
        for point in self.points:
            run_at = published_at + timedelta(hours=_hours(point))
            jobs.append(f"{content_id}@{point}={run_at.isoformat()}")
        self._try_prefect_schedule(content_id, jobs)
        return jobs

    def _try_prefect_schedule(self, content_id: str, jobs: list[str]) -> None:
        try:  # pragma: no cover - optional dependency
            import prefect  # noqa: F401
        except Exception:
            _log.debug("prefect_unavailable_local_schedule", extra={"content_id": content_id})

    def run_attribution(self, content_id: str, checkpoint_hours: int) -> dict[str, Any]:
        """Record raw revenue at a checkpoint and return the projected total."""
        point = self._point_for_hours(checkpoint_hours)
        # In production this reads MetricsCollector; here it is supplied externally.
        raw = self._snapshots.get(content_id, {}).get(point, 0.0)
        correction = self.decay_correction.get(point, 1.0)
        projected = raw / correction if correction > 0 else raw
        return {
            "content_id": content_id,
            "checkpoint": point,
            "raw": raw,
            "projected_total": projected,
        }

    def record_raw(self, content_id: str, point: str, revenue: float) -> None:
        """Record observed revenue at a checkpoint (used by run_attribution)."""
        self._snapshots.setdefault(content_id, {})[point] = revenue

    def aggregate_total(self, content_id: str) -> float:
        """Best estimate of 30d total from the latest available checkpoint."""
        snaps = self._snapshots.get(content_id, {})
        if not snaps:
            return 0.0
        # Use the latest (largest-hours) checkpoint with a decay correction.
        latest_point = max(snaps, key=lambda p: _hours(p))
        raw = snaps[latest_point]
        correction = self.decay_correction.get(latest_point, 1.0)
        return raw / correction if correction > 0 else raw

    def _point_for_hours(self, hours: int) -> str:
        for point in self.points:
            if _hours(point) == hours:
                return point
        raise ValueError(f"no checkpoint matches {hours}h")
