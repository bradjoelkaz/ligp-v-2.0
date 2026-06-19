"""Celery application for distributed async content generation (Phase 17).

Replaces the in-memory FastAPI ``BackgroundTasks`` queue (which loses pending
work on API restart) with a durable Redis-backed Celery queue, so generation
survives restarts and scales horizontally across worker processes/containers.

Run a worker with::

    celery -A orchestration.celery_app worker --loglevel=info

Configuration is environment-driven:

* ``CELERY_BROKER_URL``        broker URL      (default ``redis://localhost:6379/0``)
* ``CELERY_RESULT_BACKEND``    result backend  (default = broker URL)
* ``CELERY_TASK_ALWAYS_EAGER`` when truthy, tasks run inline/synchronously in
  the calling process with no broker — used by the test-suite so the queue can
  be exercised fully offline (no Redis required).

``celery`` is imported at module top, so this module is only imported where
Celery is installed (the worker entrypoint, and lazily from the API route /
tests). The rest of the app never imports it, preserving the offline,
dependency-light import guarantee.
"""

import os

from celery import Celery


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", BROKER_URL)

app = Celery("iigp", broker=BROKER_URL, backend=RESULT_BACKEND)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Inline execution for tests/local dev when no broker is available.
    task_always_eager=_truthy(os.getenv("CELERY_TASK_ALWAYS_EAGER")),
    task_eager_propagates=True,
    # Reliability: re-queue if a worker dies mid-task; one task per worker fetch.
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

# Discover @app.task definitions in orchestration.tasks.
app.autodiscover_tasks(["orchestration"])
