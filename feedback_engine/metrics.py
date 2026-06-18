"""Metrics collection (QA-028).

Records per-content performance metrics as JSON-lines under ``data/events`` and
exposes latest + time-series reads. Pure stdlib.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from utils.helpers import utcnow_iso
from utils.logger import get_logger

_log = get_logger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DIR = _REPO_ROOT / "data" / "events"

_METRIC_KEYS = (
    "views",
    "clicks",
    "ctr",
    "watch_time",
    "shares",
    "revenue_est",
    "attributed_revenue",
)


class MetricsCollector:
    """Append-only metrics store keyed by content id."""

    def __init__(self, store_dir: Path | str | None = None) -> None:
        self.store_dir = Path(store_dir) if store_dir else _DEFAULT_DIR

    def _path(self, content_id: str) -> Path:
        safe = content_id.replace("/", "_").replace(":", "_")
        return self.store_dir / f"metrics_{safe}.jsonl"

    def record(self, content_id: str, platform: str, metrics: dict[str, Any]) -> None:
        """Append a metrics snapshot for a content item."""
        self.store_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "content_id": content_id,
            "platform": platform,
            "ts": utcnow_iso(),
            **{k: metrics.get(k) for k in _METRIC_KEYS if k in metrics},
        }
        with self._path(content_id).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def get_latest(self, content_id: str) -> dict[str, Any]:
        """Return the most recent metrics snapshot (or empty dict)."""
        series = self.get_time_series(content_id)
        return series[-1] if series else {}

    def get_time_series(self, content_id: str, days: int = 30) -> list[dict[str, Any]]:
        """Return all recorded snapshots for a content id (most-recent last)."""
        path = self._path(content_id)
        if not path.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out
