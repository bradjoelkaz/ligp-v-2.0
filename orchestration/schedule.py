"""Production scheduling + resilient run wrapper (Phase 9).

- :func:`register_prefect_schedule` registers the daily pipeline as a Prefect
  deployment on an interval schedule (default every 6h). It degrades to logging
  guidance when Prefect is not installed, so importing this module is always safe.
- :func:`run_with_recovery` runs the pipeline defensively: on any failure it
  alerts (Slack, best-effort) and recovers the last calibrated weights + topic
  cards from the local SQLite store so the service keeps serving prior state
  instead of crashing.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from utils.logger import get_logger

_log = get_logger(__name__)

DEFAULT_INTERVAL_HOURS = int(os.getenv("PIPELINE_INTERVAL_HOURS", "6"))


def register_prefect_schedule(interval_hours: int = DEFAULT_INTERVAL_HOURS) -> dict[str, Any]:
    """Register the daily pipeline flow on an interval schedule (best-effort).

    Returns a status dict describing what happened. Never raises.
    """
    try:
        from datetime import timedelta

        from prefect import flow  # noqa: F401
        from prefect.client.schemas.schedules import IntervalSchedule

        from orchestration.flows.daily_pipeline import daily_pipeline

        schedule = IntervalSchedule(interval=timedelta(hours=interval_hours))
        flow_fn = flow(name="iigp-daily-pipeline")(daily_pipeline)
        flow_fn.serve(name="iigp-daily-deployment", schedule=schedule)
        _log.info("prefect_schedule_registered", extra={"interval_hours": interval_hours})
        return {"scheduled": True, "engine": "prefect", "interval_hours": interval_hours}
    except Exception as exc:  # noqa: BLE001 - prefect optional / serve blocks
        _log.warning(
            "prefect_unavailable_use_cron",
            extra={"interval_hours": interval_hours, "error": str(exc)},
        )
        cron = f"0 */{interval_hours} * * *"
        return {
            "scheduled": False,
            "engine": "cron",
            "interval_hours": interval_hours,
            "cron": cron,
            "command": "python -m orchestration.flows.daily_pipeline",
        }


def _alert(title: str, message: str) -> None:
    """Send a best-effort Slack alert (sync wrapper; never raises)."""
    try:
        import asyncio

        from utils.notifier import SlackNotifier

        async def _send() -> None:
            await SlackNotifier().send(title, message, level="error")

        asyncio.run(_send())
    except Exception as exc:  # noqa: BLE001
        _log.warning("alert_send_failed", extra={"error": str(exc)})


def _recover_from_store(store: Any | None) -> dict[str, Any]:
    """Load the last good weights + topic cards from the SQLite store."""
    if store is None:
        from database import db_store as store
    try:
        store.init_db()
        return {
            "weights": store.load_weights(),
            "topics": store.get_latest_trends(limit=10),
        }
    except Exception as exc:  # noqa: BLE001
        _log.error("recovery_load_failed", extra={"error": str(exc)})
        return {"weights": {}, "topics": []}


def run_with_recovery(
    runner: Callable[[], Any] | None = None,
    *,
    store: Any | None = None,
    alerter: Callable[[str, str], None] | None = None,
) -> dict[str, Any]:
    """Run the pipeline; on failure, alert + recover last good state from DB.

    ``runner`` defaults to the live ``daily_pipeline``. Returns
    ``{"ok": True, "result": ...}`` on success, or
    ``{"ok": False, "error": ..., "recovered": {...}}`` on failure.
    """
    if runner is None:
        from orchestration.flows.daily_pipeline import daily_pipeline as runner
    alert = alerter or _alert

    try:
        result = runner()
        _log.info("pipeline_run_ok")
        return {"ok": True, "result": result}
    except Exception as exc:  # noqa: BLE001 - resilience is the whole point
        _log.error("pipeline_run_failed_recovering", extra={"error": str(exc)})
        alert(
            "\u274c IIGP \ud30c\uc774\ud504\ub77c\uc778 \uc2e4\ud328",
            f"\uc624\ub958: {str(exc)[:300]}",
        )
        recovered = _recover_from_store(store)
        return {"ok": False, "error": str(exc), "recovered": recovered}
