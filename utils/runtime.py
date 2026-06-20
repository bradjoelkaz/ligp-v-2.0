"""Runtime mode helpers (Phase 9 production cutover).

Centralizes the "are we in production?" decision so modules can switch off the
offline *mock* fallbacks and require real API calls / surface real errors.

Resolution order for the environment:
1. ``APP_ENV`` environment variable (``production`` | ``staging`` | ``development``)
2. ``settings.yaml -> app.env`` (best-effort)
3. default ``development``

In production, mocks are disabled unless ``IIGP_ALLOW_MOCK=1`` is set explicitly
(useful for smoke tests against a prod-like config).
"""

from __future__ import annotations

import os


def app_env() -> str:
    """Return the current environment name (lowercased)."""
    env = os.getenv("APP_ENV")
    if not env:
        try:
            from utils.config_loader import load_config

            env = str(load_config("settings").get("app", {}).get("env") or "")
        except Exception:  # noqa: BLE001 - config must never break runtime checks
            env = ""
    return (env or "development").strip().lower()


def is_production() -> bool:
    """True when running in the production environment."""
    return app_env() == "production"


def mock_allowed() -> bool:
    """Whether offline/mock fallbacks may be used.

    Allowed outside production, or anywhere ``IIGP_ALLOW_MOCK=1`` is set.
    """
    if os.getenv("IIGP_ALLOW_MOCK", "").strip() in ("1", "true", "True"):
        return True
    return not is_production()
