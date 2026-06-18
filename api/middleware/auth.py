"""IIGP v2.0 — API key authentication middleware (Phase 9 / DD-012).

When the ``API_SECRET_KEY`` environment variable is set, every non-public route
requires a matching ``X-API-Key`` request header. When it is empty/unset the
middleware is a transparent pass-through (development mode).

Public paths bypass authentication: liveness/readiness/version probes, the
Prometheus ``/metrics`` endpoint, the admin dashboard, the OpenAPI docs and the
service root.

Implemented as a pure-ASGI callable so importing this module never requires a
web framework; Starlette's ``JSONResponse`` is imported lazily only on reject.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Awaitable, MutableMapping

    Scope = MutableMapping[str, Any]
    Message = MutableMapping[str, Any]
    Receive = Callable[[], Awaitable[Message]]
    Send = Callable[[Message], Awaitable[None]]

# Paths reachable without authentication (prefix match).
PUBLIC_PREFIXES: tuple[str, ...] = (
    "/health",
    "/ready",
    "/version",
    "/metrics",
    "/admin",
    "/docs",
    "/redoc",
    "/openapi.json",
)

_API_KEY: str | None = None


def _get_api_key() -> str | None:
    """Load the configured API key from the environment (cached after first read)."""
    global _API_KEY
    if _API_KEY is None:
        _API_KEY = os.getenv("API_SECRET_KEY", "") or None
    return _API_KEY


def _is_public(path: str) -> bool:
    return path == "/" or any(path.startswith(p) for p in PUBLIC_PREFIXES)


class APIKeyMiddleware:
    """Pure-ASGI middleware validating the ``X-API-Key`` header."""

    def __init__(self, app: Callable[..., Any]) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if _is_public(path):
            await self.app(scope, receive, send)
            return

        api_key = _get_api_key()
        if not api_key:
            # No key configured -> authentication disabled (dev mode).
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        request_key = headers.get(b"x-api-key", b"").decode("utf-8", errors="ignore")
        if request_key != api_key:
            from starlette.responses import JSONResponse

            response = JSONResponse({"detail": "Invalid or missing API key"}, status_code=401)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
