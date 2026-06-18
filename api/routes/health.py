"""Health, readiness and version routes (module-level router).

Kept dependency-light: FastAPI is imported at module load (this module is only
imported from inside ``create_app``), but no heavy stack dependencies are
touched. Exposes a module-level ``router`` so ``api.main`` can ``include_router``.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["system"])


@router.get("/health", summary="Liveness probe")
async def health() -> dict[str, str]:
    """Liveness: the process is up and serving requests."""
    return {"status": "ok"}


@router.get("/ready", summary="Readiness probe")
async def ready() -> dict[str, object]:
    """Readiness: minimal dependency check (extended in later phases)."""
    checks = {"config": _config_ok()}
    ready_state = all(checks.values())
    return {"ready": ready_state, "checks": checks}


@router.get("/version", summary="Build/version info")
async def version() -> dict[str, str]:
    """Report the application name and version from settings (with fallback)."""
    name, ver = "iigp", "2.0.0"
    try:
        from utils.config_loader import load_config

        app_cfg = load_config("settings").get("app", {})
        name = app_cfg.get("name", name)
        ver = app_cfg.get("version", ver)
    except Exception:  # noqa: BLE001 - version endpoint must not fail hard
        pass
    return {"name": name, "version": ver}


def _config_ok() -> bool:
    try:
        from utils.config_loader import load_config

        return bool(load_config("settings"))
    except Exception:  # noqa: BLE001
        return False
