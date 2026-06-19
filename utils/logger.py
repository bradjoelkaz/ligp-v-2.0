"""Structured JSON logging for IIGP v2.0 (Layer 0 observability, utils/logger.py).

Emits one JSON object per log line so logs are machine-parseable by the
observability stack (Prometheus/Loki/Grafana). Depends only on the stdlib.

Usage:
    from utils.logger import get_logger
    log = get_logger(__name__)
    log.info("collected items", extra={"platform": "rss", "count": 42})
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
from typing import Any

# Reserved LogRecord attributes that should not be duplicated into the JSON body.
_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()) | {
    "message",
    "asctime",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON documents."""

    def __init__(self, *, include_trace_id: bool = True) -> None:
        super().__init__()
        self.include_trace_id = include_trace_id

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)

        # Merge any structured fields passed via `extra=`.
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value

        if self.include_trace_id and "trace_id" not in payload:
            trace_id = os.environ.get("IIGP_TRACE_ID")
            if trace_id:
                payload["trace_id"] = trace_id

        return json.dumps(payload, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    """Human-friendly fallback used when LOG_FORMAT=text."""

    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)s %(name)s: %(message)s")


def _build_handler() -> logging.Handler:
    handler = logging.StreamHandler(stream=sys.stdout)
    fmt = os.environ.get("LOG_FORMAT", "json").lower()
    handler.setFormatter(TextFormatter() if fmt == "text" else JsonFormatter())
    return handler


def get_logger(name: str = "iigp") -> logging.Logger:
    """Return a configured logger; idempotent across repeated calls."""
    logger = logging.getLogger(name)
    if not getattr(logger, "_iigp_configured", False):
        level = os.environ.get("LOG_LEVEL", "INFO").upper()
        logger.setLevel(getattr(logging, level, logging.INFO))
        logger.addHandler(_build_handler())
        logger.propagate = False
        logger._iigp_configured = True  # type: ignore[attr-defined]
    return logger
