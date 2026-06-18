"""IIGP v2.0 — background worker entrypoint.

Runs as the docker-compose ``worker`` service. Acts as a Prefect agent (picks
up flow runs from the queue) when Prefect is available; otherwise falls back to
a simple polling loop that runs the daily pipeline every 10 minutes.
"""

from __future__ import annotations

import os
import sys

from utils.logger import get_logger

logger = get_logger(__name__)


def main() -> None:
    """Worker main loop."""
    prefect_url = os.getenv("PREFECT_API_URL", "http://prefect:4200/api")
    logger.info("worker_starting", extra={"prefect_url": prefect_url})

    try:
        # lazy: importable even where Prefect is absent
        from prefect.runner import Runner  # type: ignore[import-not-found]

        runner = Runner()
        runner.start()
    except ImportError:
        logger.warning("prefect_not_installed_polling_mode")
        _polling_loop()
    except Exception as exc:  # noqa: BLE001 - top-level guard
        logger.error("worker_crashed", extra={"error": str(exc)})
        sys.exit(1)


def _polling_loop() -> None:
    """Simple polling loop used when Prefect is unavailable (dev mode)."""
    import time

    from orchestration.flows.daily_pipeline import run_daily_pipeline

    logger.info("polling_loop_started")
    while True:  # pragma: no cover - infinite loop, exercised in deployment only
        try:
            run_daily_pipeline([])
        except Exception as exc:  # noqa: BLE001
            logger.error("pipeline_run_failed", extra={"error": str(exc)})
        time.sleep(600)  # 10 minutes


if __name__ == "__main__":  # pragma: no cover
    main()
