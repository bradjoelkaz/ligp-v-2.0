"""Prometheus observability for the IIGP API (Layer 0 / QA-028).

This module exposes a *pure-ASGI* middleware so it can be imported without
FastAPI/Starlette being installed, and the ``prometheus_client`` dependency is
imported lazily. When ``prometheus_client`` is unavailable the middleware
degrades to a transparent pass-through and ``render_latest`` returns a small
plaintext fallback, so the whole module stays import-safe in dependency-light
environments (CI installs the real package; production scrapes ``/metrics``).

Metrics emitted (per QA-028):
    iigp_http_requests_total{method,path,status}      Counter
    iigp_http_request_duration_seconds{method,path}   Histogram
    iigp_http_requests_in_progress{method,path}       Gauge
"""

from __future__ import annotations

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
