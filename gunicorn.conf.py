"""Gunicorn configuration for the IIGP v2.0 API (Phase 16).

Runs the FastAPI app behind Gunicorn's pre-fork master with Uvicorn workers::

    gunicorn -c gunicorn.conf.py api.main:create_app --factory

Why a config file (and not just CLI flags)? Prometheus' ``prometheus_client``
multiprocess mode writes one mmap ``*.db`` file per worker into
``PROMETHEUS_MULTIPROC_DIR``. Those files must be managed at the *master* /
worker-lifecycle boundary, never inside each worker:

* ``on_starting``  — runs ONCE in the master before any worker is forked, so it
  is the only safe place to wipe stale ``*.db`` files. Doing this per-worker
  would erase siblings' live metrics.
* ``child_exit``   — runs in the master when a worker dies; we mark that PID's
  metrics dead so the aggregated ``/metrics`` exposition stops counting a gone
  worker (and its mmap file can be reclaimed).

Everything that touches ``gunicorn``/``prometheus_client`` is imported lazily
inside the hooks, so this module imports cleanly in dependency-light
environments (unit tests import it without gunicorn installed).
"""

import os

# -- Server socket ------------------------------------------------------------
bind = os.getenv("GUNICORN_BIND", "0.0.0.0:8000")

# -- Worker processes ---------------------------------------------------------
workers = int(os.getenv("GUNICORN_WORKERS", "4"))
worker_class = "uvicorn.workers.UvicornWorker"

# -- Timeouts / logging -------------------------------------------------------
timeout = int(os.getenv("GUNICORN_TIMEOUT", "60"))
graceful_timeout = int(os.getenv("GUNICORN_GRACEFUL_TIMEOUT", "30"))
accesslog = os.getenv("GUNICORN_ACCESSLOG", "-")
errorlog = os.getenv("GUNICORN_ERRORLOG", "-")
loglevel = os.getenv("GUNICORN_LOGLEVEL", "info")


# -- Lifecycle hooks (Prometheus multiprocess wiring) -------------------------
def on_starting(server):
    """Master-only startup hook: clear stale Prometheus multiprocess files.

    Runs exactly once in the master process before any worker is forked, so it
    is the only safe place to wipe ``PROMETHEUS_MULTIPROC_DIR``. Exception-safe:
    a metrics-cleanup failure must never prevent the server from starting.
    """
    try:
        from api.metrics import cleanup_multiprocess_dir

        cleanup_multiprocess_dir()
    except Exception:  # noqa: BLE001 - never block startup on metrics cleanup
        pass


def child_exit(server, worker):
    """Master hook fired when a worker exits: mark that worker's metrics dead.

    Tells ``prometheus_client`` to invalidate the dead worker's mmap samples so
    the aggregated exposition stops attributing gauges/counters to a process
    that no longer exists. No-op when prometheus is not installed or when
    multiprocess mode is disabled.
    """
    try:
        from prometheus_client import multiprocess

        multiprocess.mark_process_dead(worker.pid)
    except Exception:  # noqa: BLE001 - metrics bookkeeping must never crash exit
        pass
