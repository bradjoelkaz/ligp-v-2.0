"""Celery tasks for distributed content generation (Phase 17 + Phase 19).

Phase 17 introduced ``generate_content_task`` as a thin wrapper around the
async generation worker. Phase 19 adds **resilience**:

* **Auto-retry with exponential backoff + jitter** (``autoretry_for``) for
  *transient* failures (network blips, DB connection delays). Permanent errors
  (e.g. bad input -> ``ValueError``) are NOT retried and fail fast.
* **A failure hook** (``DatabaseAlertTask.on_failure``) that records the final
  ``status='failed'`` in the DB once retries are exhausted (or for a
  non-retryable error). This separates the "record the outcome" concern from
  the task body and acts as a lightweight dead-letter handler.

Unlike Phase 17 (which reused the swallow-everything ``_process_content``), the
task body here lets exceptions **propagate** so Celery can decide to retry; the
DB ``failed`` write is owned by ``on_failure``. The in-process BackgroundTasks
fallback in ``api.routes.content`` still uses ``_process_content`` unchanged.

Why ``asyncio.run`` is safe: a Celery worker has no running event loop, so a
fresh loop per task is correct (avoids "event loop already running").
"""

import asyncio
import json
from typing import Any

from celery import Task

from orchestration.celery_app import app
from utils.logger import get_logger

_log = get_logger(__name__)

# Transient errors worth retrying. httpx is optional at import time (present in
# CI/worker requirements); builtin network errors cover DB/socket blips.
try:  # pragma: no cover - import shape depends on environment
    import httpx

    _HTTPX_ERRORS: tuple[type[BaseException], ...] = (httpx.RequestError,)
except Exception:  # pragma: no cover - httpx not installed -> builtins only
    _HTTPX_ERRORS = ()

RETRYABLE_ERRORS: tuple[type[BaseException], ...] = _HTTPX_ERRORS + (
    ConnectionError,
    TimeoutError,
    OSError,
)


class DatabaseAlertTask(Task):
    """Custom base Task: on permanent failure, record ``failed`` in the DB."""

    def on_failure(self, exc, task_id, args, kwargs, einfo):  # noqa: ANN001
        """Record the terminal failure (after retries are exhausted)."""
        content_id = args[0] if args else None
        if content_id is not None:
            _log.error(
                "celery_task_failed_permanently",
                extra={"task_id": task_id, "content_id": content_id, "error": str(exc)},
            )
            try:
                from api.routes.content import _update_status

                _update_status(content_id, "failed", error=json.dumps({"error": str(exc)}))
            except Exception as db_exc:  # noqa: BLE001 - never raise from the hook
                _log.critical(
                    "celery_failure_db_record_failed",
                    extra={"content_id": content_id, "error": str(db_exc)},
                )
        super().on_failure(exc, task_id, args, kwargs, einfo)


def _generate_sync(content_id: str, req_data: dict[str, Any]) -> None:
    """Synchronous generation core that PROPAGATES exceptions (for retry).

    Drives ``processing -> completed``; on any exception it re-raises so Celery
    can retry (transient) or fail the task (permanent), with the DB ``failed``
    write handled by ``DatabaseAlertTask.on_failure``.
    """
    from api.routes.content import _update_status

    node_id = str(req_data.get("node_id", ""))
    name = str(req_data.get("name", "") or "")
    platform = str(req_data.get("platform", "blog") or "blog")
    tags = list(req_data.get("tags", []) or [])

    _update_status(content_id, "processing")

    from content_factory.generators.blog_generator import BlogGenerator
    from content_factory.quality_gate import QualityGate

    node = {"id": node_id, "name": name or node_id, "tags": tags}
    content = asyncio.run(BlogGenerator().generate_async(node, platform))
    passed, issues = QualityGate().check(content, platform)
    content["quality_passed"] = passed
    content["quality_issues"] = issues
    _update_status(content_id, "completed", result=json.dumps(content, default=str))

    from api.metrics import record_content_generated

    record_content_generated(platform, passed)


@app.task(
    bind=True,
    base=DatabaseAlertTask,
    name="orchestration.tasks.generate_content_task",
    max_retries=5,
    autoretry_for=RETRYABLE_ERRORS,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
)
def generate_content_task(self, content_id: str, req_data: dict[str, Any]) -> str:
    """Generate content for ``content_id`` (retries transient errors).

    Args:
        content_id: pre-persisted ('pending') content row id to drive.
        req_data: JSON-safe request (``node_id``, ``name``, ``platform``, ``tags``).

    Returns:
        The ``content_id`` (Celery result / chaining handle).
    """
    _log.info(
        "celery_generate_start",
        extra={"content_id": content_id, "retry": self.request.retries},
    )
    _generate_sync(content_id, req_data)
    _log.info("celery_generate_done", extra={"content_id": content_id})
    return content_id
