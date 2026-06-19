"""Prometheus observability for the IIGP API (Layer 0 / QA-028).

This module exposes a *pure-ASGI* middleware so it can be imported without
FastAPI/Starlette being installed, and the ``prometheus_client`` dependency is
imported lazily. When ``prometheus_client`` is unavailable the middleware
degrades to a transparent pass-through and ``render_latest`` returns a small
plaintext fallback, so the whole module stays import-safe in dependency-light
environments (CI installs the real package; production scrapes ``/metrics``).

HTTP metrics (per QA-028):
    iigp_http_requests_total{method,path,status}      Counter
    iigp_http_request_duration_seconds{method,path}   Histogram
    iigp_http_requests_in_progress{method,path}       Gauge

Business metrics (Phase 9):
    iigp_graph_nodes                                  Gauge
    iigp_graph_edges                                  Gauge
    iigp_content_generated_total{platform,quality}    Counter
    iigp_pipeline_runs_total{pipeline,status}         Counter
    iigp_pipeline_duration_seconds{pipeline}          Histogram
    iigp_collector_documents_total{source,status}     Counter

NOTE on multi-process exposure: prometheus_client metrics are per-process. The
API process serves ``/metrics`` with its own registry, so business metrics
recorded inside the worker process (e.g. the daily pipeline) are NOT visible on
the API's ``/metrics``. To surface worker metrics in a deployed stack, run the
worker with a Pushgateway or its own metrics HTTP server (documented follow-up).
The recording calls below are correct regardless and are exercised in-process by
the API routes and the integration tests.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from collections.abc import Awaitable, MutableMapping

    Scope = MutableMapping[str, Any]
    Message = MutableMapping[str, Any]
    Receive = Callable[[], Awaitable[Message]]
    Send = Callable[[Message], Awaitable[None]]

# Default histogram buckets (seconds) tuned for sub-second web latencies.
DEFAULT_BUCKETS: tuple[float, ...] = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
)

_FALLBACK_BODY = b"# prometheus_client is not installed; metrics are disabled.\n"

# Histogram buckets (seconds) for pipeline runs — coarser than HTTP latencies.
PIPELINE_BUCKETS: tuple[float, ...] = (
    0.1,
    0.5,
    1.0,
    5.0,
    10.0,
    30.0,
    60.0,
    120.0,
    300.0,
    600.0,
)


class _Metrics:
    """Lazily-instantiated container for the Prometheus collectors.

    Instantiation is deferred until first use so importing this module never
    requires ``prometheus_client``. If the dependency is missing, ``available``
    stays ``False`` and every record call is a no-op.
    """

    def __init__(self) -> None:
        self.available = False
        self.registry: Any = None
        self._requests_total: Any = None
        self._request_duration: Any = None
        self._in_progress: Any = None
        # Business collectors (Phase 9).
        self._graph_nodes: Any = None
        self._graph_edges: Any = None
        self._content_generated: Any = None
        self._pipeline_runs: Any = None
        self._pipeline_duration: Any = None
        self._collector_docs: Any = None
        self._content_type = "text/plain; version=0.0.4; charset=utf-8"
        self._generate_latest: Callable[[Any], bytes] | None = None

    def setup(self, registry: Any = None) -> None:
        """Build the collectors. Safe to call repeatedly (idempotent)."""
        if self.available:
            return
        try:
            from prometheus_client import (
                CONTENT_TYPE_LATEST,
                CollectorRegistry,
                Counter,
                Gauge,
                Histogram,
                generate_latest,
            )
        except ImportError:
            self.available = False
            return

        self.registry = registry if registry is not None else CollectorRegistry()
        self._requests_total = Counter(
            "iigp_http_requests_total",
            "Total HTTP requests processed by the IIGP API.",
            labelnames=("method", "path", "status"),
            registry=self.registry,
        )
        self._request_duration = Histogram(
            "iigp_http_request_duration_seconds",
            "HTTP request latency in seconds.",
            labelnames=("method", "path"),
            buckets=DEFAULT_BUCKETS,
            registry=self.registry,
        )
        self._in_progress = Gauge(
            "iigp_http_requests_in_progress",
            "Number of HTTP requests currently being served.",
            labelnames=("method", "path"),
            registry=self.registry,
        )
        # -- Business collectors (Phase 9) -----------------------------------
        self._graph_nodes = Gauge(
            "iigp_graph_nodes",
            "Current number of nodes in the knowledge graph.",
            registry=self.registry,
        )
        self._graph_edges = Gauge(
            "iigp_graph_edges",
            "Current number of edges in the knowledge graph.",
            registry=self.registry,
        )
        self._content_generated = Counter(
            "iigp_content_generated_total",
            "Content items produced by the content factory.",
            labelnames=("platform", "quality"),
            registry=self.registry,
        )
        self._pipeline_runs = Counter(
            "iigp_pipeline_runs_total",
            "Pipeline runs by name and outcome.",
            labelnames=("pipeline", "status"),
            registry=self.registry,
        )
        self._pipeline_duration = Histogram(
            "iigp_pipeline_duration_seconds",
            "Pipeline run duration in seconds.",
            labelnames=("pipeline",),
            buckets=PIPELINE_BUCKETS,
            registry=self.registry,
        )
        self._collector_docs = Counter(
            "iigp_collector_documents_total",
            "Documents fetched by collectors, by source and outcome.",
            labelnames=("source", "status"),
            registry=self.registry,
        )
        self._content_type = CONTENT_TYPE_LATEST
        self._generate_latest = generate_latest
        self.available = True

    # -- recording helpers (all no-op when unavailable) ----------------------

    def track_in_progress(self, method: str, path: str, delta: int) -> None:
        if self.available:
            self._in_progress.labels(method=method, path=path).inc(delta)

    def observe(self, method: str, path: str, status: int, duration: float) -> None:
        if not self.available:
            return
        self._requests_total.labels(method=method, path=path, status=str(status)).inc()
        self._request_duration.labels(method=method, path=path).observe(duration)

    # -- business recording helpers (all no-op when unavailable) -------------

    def set_graph_size(self, nodes: int, edges: int) -> None:
        if self.available:
            self._graph_nodes.set(nodes)
            self._graph_edges.set(edges)

    def inc_content(self, platform: str, passed: bool) -> None:
        if self.available:
            quality = "passed" if passed else "failed"
            self._content_generated.labels(platform=platform, quality=quality).inc()

    def observe_pipeline(self, pipeline: str, status: str, duration: float) -> None:
        if self.available:
            self._pipeline_runs.labels(pipeline=pipeline, status=status).inc()
            self._pipeline_duration.labels(pipeline=pipeline).observe(duration)

    def inc_collector(self, source: str, status: str, count: int = 1) -> None:
        if self.available and count:
            self._collector_docs.labels(source=source, status=status).inc(count)

    def snapshot(self) -> dict[str, float]:
        """Current scalar values of key metrics (0.0 for each when unavailable).

        Used by the admin dashboard to show live, in-process operational numbers.
        Counter/gauge samples are summed across label combinations.
        """
        snap = {
            "graph_nodes": 0.0,
            "graph_edges": 0.0,
            "http_requests_total": 0.0,
            "http_requests_in_progress": 0.0,
            "content_generated_total": 0.0,
            "pipeline_runs_total": 0.0,
        }
        if not self.available:
            return snap
        sums = {
            "iigp_http_requests_total": "http_requests_total",
            "iigp_http_requests_in_progress": "http_requests_in_progress",
            "iigp_content_generated_total": "content_generated_total",
            "iigp_pipeline_runs_total": "pipeline_runs_total",
        }
        for metric in self.registry.collect():
            for sample in metric.samples:
                if sample.name == "iigp_graph_nodes":
                    snap["graph_nodes"] = sample.value
                elif sample.name == "iigp_graph_edges":
                    snap["graph_edges"] = sample.value
                elif sample.name in sums:
                    snap[sums[sample.name]] += sample.value
        return snap

    def render_latest(self) -> tuple[bytes, str]:
        """Return ``(body, content_type)`` for the ``/metrics`` endpoint."""
        if self.available and self._generate_latest is not None:
            return self._generate_latest(self.registry), self._content_type
        return _FALLBACK_BODY, "text/plain; charset=utf-8"


# Module-level singleton shared by the middleware and the /metrics route.
METRICS = _Metrics()


def setup_metrics(registry: Any = None) -> _Metrics:
    """Initialise the shared metrics registry and return it (idempotent)."""
    METRICS.setup(registry)
    return METRICS


def render_latest() -> tuple[bytes, str]:
    """Render the current metrics exposition (lazy-initialises on first call)."""
    if not METRICS.available:
        METRICS.setup()
    return METRICS.render_latest()


def _ensure() -> None:
    if not METRICS.available:
        METRICS.setup()


def record_graph_size(nodes: int, edges: int) -> None:
    """Set the current graph node/edge gauges (no-op without prometheus)."""
    _ensure()
    METRICS.set_graph_size(nodes, edges)


def record_content_generated(platform: str, passed: bool) -> None:
    """Increment the content-generated counter for ``platform`` and outcome."""
    _ensure()
    METRICS.inc_content(platform, passed)


def record_pipeline_run(pipeline: str, status: str, duration: float) -> None:
    """Record a pipeline run (count by status + duration histogram)."""
    _ensure()
    METRICS.observe_pipeline(pipeline, status, duration)


def record_collector(source: str, status: str, count: int = 1) -> None:
    """Increment the collector document counter for ``source`` and outcome."""
    _ensure()
    METRICS.inc_collector(source, status, count)


def metrics_snapshot() -> dict[str, float]:
    """Return live scalar values of key metrics for the admin dashboard."""
    _ensure()
    return METRICS.snapshot()


def push_metrics(
    job: str = "iigp-worker",
    gateway: str | None = None,
    grouping_key: dict[str, str] | None = None,
) -> bool:
    """Push the current registry to a Prometheus Pushgateway.

    Long-running / batch worker processes cannot be scraped directly, so they
    push their metrics to a Pushgateway that Prometheus scrapes instead. The
    gateway address defaults to ``$PUSHGATEWAY_URL`` (or ``localhost:9091``).

    Returns ``True`` on success. Never raises: missing ``prometheus_client`` or
    an unreachable gateway are swallowed so a metrics failure can never crash
    the worker.
    """
    _ensure()
    if not METRICS.available:
        return False
    try:
        from prometheus_client import push_to_gateway

        gw = gateway or os.getenv("PUSHGATEWAY_URL", "localhost:9091")
        push_to_gateway(gw, job=job, registry=METRICS.registry, grouping_key=grouping_key)
        return True
    except Exception as exc:  # noqa: BLE001 - metrics must never crash the worker
        try:
            from utils.logger import get_logger

            get_logger("iigp.metrics").warning(
                "pushgateway_push_failed", extra={"error": str(exc), "job": job}
            )
        except Exception:  # pragma: no cover - logging must not raise
            pass
        return False


def normalize_path(scope: Scope) -> str:
    """Resolve a low-cardinality path label for an ASGI scope.

    Prefers the matched route template (``scope['route'].path``) so that
    parameterised routes like ``/admin/api/node/{node_id}`` collapse to a single
    series instead of exploding cardinality per id.
    """
    route = scope.get("route")
    template = getattr(route, "path", None)
    if isinstance(template, str) and template:
        return template
    raw = scope.get("path", "/")
    return raw if isinstance(raw, str) and raw else "/"


class PrometheusMiddleware:
    """Pure-ASGI middleware that records request count, latency and concurrency.

    Implemented as a plain ASGI callable (no Starlette ``BaseHTTPMiddleware``
    subclassing) so the module imports cleanly without web dependencies. When
    Prometheus is unavailable it simply forwards the call.
    """

    def __init__(self, app: Callable[..., Any]) -> None:
        self.app = app
        METRICS.setup()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        path = normalize_path(scope)
        status_holder = {"code": 500}

        async def send_wrapper(message: Message) -> None:
            if message.get("type") == "http.response.start":
                status_holder["code"] = message.get("status", 500)
            await send(message)

        METRICS.track_in_progress(method, path, 1)
        start = time.perf_counter()
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration = time.perf_counter() - start
            METRICS.track_in_progress(method, path, -1)
            METRICS.observe(method, path, status_holder["code"], duration)
