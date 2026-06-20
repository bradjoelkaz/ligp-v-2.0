"""Health-check logic (Phase 12), framework-free so it is unit-testable offline.

The FastAPI ``/health`` route in :mod:`api.routes.health` is a thin wrapper over
:func:`health_report`. DB/metrics probes are lazy and never raise.
"""

from __future__ import annotations

import os
from typing import Any

from utils.helpers import utcnow_iso
from utils.logger import get_logger

_log = get_logger(__name__)


def check_database() -> str:
    """Probe the database with ``SELECT 1``.

    Returns ``"not_configured"`` when ``DATABASE_URL`` is unset (DB is optional —
    not an error), ``"connected"`` on success, ``"disconnected"`` on any failure.
    """
    url = os.getenv("DATABASE_URL")
    if not url:
        return "not_configured"
    try:
        from database.db_adapter import DBAdapter

        db = DBAdapter(url)
        try:
            db.execute("SELECT 1")
            return "connected"
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001 - health probe must never raise
        _log.warning("health_db_check_failed", extra={"error": str(exc)})
        return "disconnected"


def check_metrics() -> str:
    """Report whether the Prometheus collectors are active."""
    try:
        from api.metrics import METRICS

        return "enabled" if METRICS.available else "disabled"
    except Exception:  # noqa: BLE001
        return "disabled"


def check_asset_store() -> str:
    """Probe the local SQLite asset store (Phase 9).

    Returns ``"ok"`` when all expected tables are present, ``"degraded"`` when
    some are missing, ``"error"`` on failure. Never raises.
    """
    try:
        from database.db_store import health_check

        report = health_check()
        if report.get("error"):
            return "error"
        return "ok" if report.get("ok") else "degraded"
    except Exception as exc:  # noqa: BLE001
        _log.warning("health_asset_store_check_failed", extra={"error": str(exc)})
        return "error"


def health_report() -> tuple[dict[str, Any], bool]:
    """Build the health payload and an ``is_healthy`` flag.

    Only a *configured-but-unreachable* database marks the service unhealthy;
    a missing ``DATABASE_URL`` or disabled metrics do not (both are optional).
    The asset-store status is reported for visibility but is non-fatal.
    """
    components = {
        "database": check_database(),
        "metrics": check_metrics(),
        "asset_store": check_asset_store(),
    }
    healthy = components["database"] != "disconnected"
    body = {
        "status": "healthy" if healthy else "unhealthy",
        "timestamp": utcnow_iso(),
        "components": components,
    }
    return body, healthy
