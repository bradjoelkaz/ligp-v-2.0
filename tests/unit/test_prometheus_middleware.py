"""Unit tests for the Prometheus ASGI middleware (api/metrics.py).

These run without FastAPI/Starlette: the middleware is a pure-ASGI callable and
the no-op/fallback paths exercise the dependency-light behaviour. The recording
assertions are gated behind ``importorskip('prometheus_client')`` so they run in
CI (where the package is installed) and skip cleanly in minimal environments.
"""

from __future__ import annotations

import asyncio

import pytest

from api.metrics import (
    _FALLBACK_BODY,
    DEFAULT_BUCKETS,
    PrometheusMiddleware,
    _Metrics,
    normalize_path,
    render_latest,
)


def _run_request(app, scope):
    """Drive an ASGI app once and return (collected_messages, ...)."""
    messages: list[dict] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    return messages


def _downstream(status=200, body=b"ok"):
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": status, "headers": []})
        await send({"type": "http.response.body", "body": body})

    return app


@pytest.mark.unit
def test_metrics_noop_when_prometheus_absent():
    m = _Metrics()
    assert m.available is False
    # No-op calls must never raise even without prometheus_client.
    m.track_in_progress("GET", "/x", 1)
    m.observe("GET", "/x", 200, 0.01)
    body, content_type = m.render_latest()
    assert body == _FALLBACK_BODY
    assert content_type.startswith("text/plain")


@pytest.mark.unit
def test_default_buckets_are_sorted_and_positive():
    assert list(DEFAULT_BUCKETS) == sorted(DEFAULT_BUCKETS)
    assert all(b > 0 for b in DEFAULT_BUCKETS)


@pytest.mark.unit
def test_normalize_path_prefers_route_template():
    class _Route:
        path = "/admin/api/node/{node_id}"

    assert normalize_path({"route": _Route(), "path": "/admin/api/node/42"}) == (
        "/admin/api/node/{node_id}"
    )
    assert normalize_path({"path": "/health"}) == "/health"
    assert normalize_path({}) == "/"


@pytest.mark.unit
def test_middleware_passes_through_and_captures_status():
    app = PrometheusMiddleware(_downstream(status=201, body=b"created"))
    scope = {"type": "http", "method": "POST", "path": "/health"}
    messages = _run_request(app, scope)
    assert messages[0]["type"] == "http.response.start"
    assert messages[0]["status"] == 201
    assert messages[1]["body"] == b"created"


@pytest.mark.unit
def test_middleware_ignores_non_http_scope():
    app = PrometheusMiddleware(_downstream())
    scope = {"type": "lifespan"}
    # Should forward to the downstream app without recording HTTP metrics.
    messages = _run_request(app, scope)
    assert messages[0]["type"] == "http.response.start"


@pytest.mark.unit
def test_render_latest_returns_bytes_and_content_type():
    body, content_type = render_latest()
    assert isinstance(body, bytes)
    assert isinstance(content_type, str) and content_type


@pytest.mark.unit
def test_metrics_recorded_with_prometheus():
    pytest.importorskip("prometheus_client")
    from prometheus_client import CollectorRegistry

    m = _Metrics()
    m.setup(CollectorRegistry())
    assert m.available is True

    m.track_in_progress("GET", "/health", 1)
    m.observe("GET", "/health", 200, 0.02)
    m.track_in_progress("GET", "/health", -1)

    count = m.registry.get_sample_value(
        "iigp_http_requests_total",
        {"method": "GET", "path": "/health", "status": "200"},
    )
    assert count == 1.0

    in_progress = m.registry.get_sample_value(
        "iigp_http_requests_in_progress", {"method": "GET", "path": "/health"}
    )
    assert in_progress == 0.0

    body, content_type = m.render_latest()
    assert b"iigp_http_requests_total" in body
    assert "text/plain" in content_type
