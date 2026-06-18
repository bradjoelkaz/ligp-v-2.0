"""Base collector with resilience primitives (DD-003 / QA-001 / QA-002).

Provides a self-contained, dependency-light foundation for all data
collectors:

* ``CircuitBreaker`` — opens after N consecutive failures, half-opens after a
  timeout so a single failing source cannot stall the pipeline (QA-001).
* ``TokenBucket`` — per-platform rate limiting driven by ``platforms.yaml``
  quota fields (QA-002). An optional Redis backend can be layered on later for
  distributed counting; the in-process bucket is the default and is testable.
* ``DeadLetterQueue`` — failed payloads are pushed here instead of crashing the
  worker, enabling later replay (QA-001).
* ``BaseCollector`` — async ``collect()`` template wiring the above together
  plus ``health_check()``.

The heavy/optional libs (aiohttp, redis, pybreaker) are intentionally NOT
imported here; concrete collectors import their HTTP client lazily. This keeps
the resilience core unit-testable without network access.
"""

from __future__ import annotations

import abc
import asyncio
import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from utils.helpers import utcnow_iso
from utils.logger import get_logger
from utils.retry import compute_delay

_log = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Circuit breaker (QA-001)
# --------------------------------------------------------------------------- #
class CircuitState(StrEnum):
    CLOSED = "closed"  # healthy, calls allowed
    OPEN = "open"  # failing, calls rejected fast
    HALF_OPEN = "half_open"  # probing recovery


class CircuitOpenError(RuntimeError):
    """Raised when a call is attempted while the circuit is OPEN."""


class CircuitBreaker:
    """Minimal thread-safe circuit breaker.

    Opens after ``failure_threshold`` consecutive failures and stays open for
    ``reset_timeout`` seconds, then transitions to HALF_OPEN to probe recovery.
    """

    def __init__(self, failure_threshold: int = 5, reset_timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self._state = CircuitState.CLOSED
        self._failures = 0
        self._opened_at = 0.0
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            return self._current_state()

    def _current_state(self) -> CircuitState:
        if (
            self._state == CircuitState.OPEN
            and (time.monotonic() - self._opened_at) >= self.reset_timeout
        ):
            self._state = CircuitState.HALF_OPEN
        return self._state

    def allow(self) -> bool:
        """Return True if a call may proceed."""
        with self._lock:
            return self._current_state() != CircuitState.OPEN

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._state = CircuitState.CLOSED

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._state = CircuitState.OPEN
                self._opened_at = time.monotonic()


# --------------------------------------------------------------------------- #
# Token bucket rate limiter (QA-002)
# --------------------------------------------------------------------------- #
class TokenBucket:
    """Thread-safe token bucket.

    ``capacity`` tokens refill over ``window_sec`` (e.g. api_quota_per_day over
    86400s). ``consume`` returns whether a token was available.
    """

    def __init__(self, capacity: int, window_sec: float = 86400.0):
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self.capacity = float(capacity)
        self.refill_rate = self.capacity / float(window_sec)  # tokens/sec
        self._tokens = float(capacity)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last
        self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_rate)
        self._last = now

    def consume(self, tokens: int = 1) -> bool:
        with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    @property
    def available(self) -> float:
        with self._lock:
            self._refill()
            return self._tokens


# --------------------------------------------------------------------------- #
# Dead letter queue (QA-001)
# --------------------------------------------------------------------------- #
@dataclass
class DeadLetterQueue:
    """In-memory DLQ with optional JSONL persistence for replay."""

    max_retries: int = 5
    path: Path | None = None
    _items: deque[dict[str, Any]] = field(default_factory=deque)

    def push(self, payload: dict[str, Any], error: str, retries: int = 0) -> None:
        record = {
            "ts": utcnow_iso(),
            "error": error,
            "retries": retries,
            "payload": payload,
        }
        self._items.append(record)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        _log.error("dlq_push", extra={"error": error, "retries": retries})

    def __len__(self) -> int:
        return len(self._items)

    def drain(self) -> list[dict[str, Any]]:
        items = list(self._items)
        self._items.clear()
        return items


# --------------------------------------------------------------------------- #
# Base collector
# --------------------------------------------------------------------------- #
@dataclass
class CollectorConfig:
    platform_id: str
    api_quota_per_day: int = 10000
    quota_window_sec: float = 86400.0
    backoff_strategy: str = "exponential"
    backoff_base_sec: float = 2.0
    backoff_max_sec: float = 300.0
    jitter: bool = True
    failure_threshold: int = 5
    reset_timeout_sec: float = 60.0
    max_retries: int = 5

    @classmethod
    def from_platform(
        cls, platform: dict[str, Any], defaults: dict[str, Any] | None = None
    ) -> CollectorConfig:
        """Build a config from a ``platforms.yaml`` entry + ``defaults`` block."""
        d = defaults or {}
        cb = {**d.get("circuit_breaker", {}), **platform.get("circuit_breaker", {})}
        return cls(
            platform_id=platform["platform_id"],
            api_quota_per_day=int(platform.get("api_quota_per_day", 10000)),
            quota_window_sec=float(
                platform.get("quota_window_sec", d.get("quota_window_sec", 86400))
            ),
            backoff_strategy=platform.get(
                "backoff_strategy", d.get("backoff_strategy", "exponential")
            ),
            backoff_base_sec=float(d.get("backoff_base_sec", 2)),
            backoff_max_sec=float(d.get("backoff_max_sec", 300)),
            jitter=bool(d.get("jitter", True)),
            failure_threshold=int(cb.get("failure_threshold", 5)),
            reset_timeout_sec=float(cb.get("reset_timeout_sec", 60)),
        )


class BaseCollector(abc.ABC):
    """Template for resilient async collectors.

    Subclasses implement :meth:`fetch` (the raw I/O). The base class wires in
    rate limiting, circuit breaking, retry/backoff, and DLQ handling so one
    failing source never stops the others (QA-001).
    """

    def __init__(self, config: CollectorConfig, dlq: DeadLetterQueue | None = None):
        self.config = config
        self.breaker = CircuitBreaker(config.failure_threshold, config.reset_timeout_sec)
        self.bucket = TokenBucket(config.api_quota_per_day, config.quota_window_sec)
        self.dlq = dlq or DeadLetterQueue(max_retries=config.max_retries)

    @abc.abstractmethod
    async def fetch(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Perform the raw fetch and return a list of normalized-ish records."""

    async def collect(self, **kwargs: Any) -> list[dict[str, Any]]:
        """Resilient collection entry point.

        Returns collected items (possibly empty). Never raises for expected
        transport failures: those go to the DLQ.
        """
        if not self.bucket.consume():
            _log.warning("quota_exhausted", extra={"platform": self.config.platform_id})
            return []

        if not self.breaker.allow():
            _log.warning("circuit_open", extra={"platform": self.config.platform_id})
            return []

        last_error: Exception | None = None
        for attempt in range(1, self.config.max_retries + 1):
            try:
                items = await self.fetch(**kwargs)
                self.breaker.record_success()
                return items
            except Exception as exc:  # noqa: BLE001 - collectors must not crash the pipeline
                last_error = exc
                self.breaker.record_failure()
                if attempt == self.config.max_retries or not self.breaker.allow():
                    break
                delay = compute_delay(
                    attempt,
                    strategy=self.config.backoff_strategy,
                    base=self.config.backoff_base_sec,
                    max_delay=self.config.backoff_max_sec,
                    jitter=self.config.jitter,
                )
                await asyncio.sleep(delay)

        self.dlq.push(
            {"platform": self.config.platform_id, "kwargs": kwargs},
            error=str(last_error),
            retries=self.config.max_retries,
        )
        return []

    def health_check(self) -> dict[str, Any]:
        """Return a health snapshot for the observability layer."""
        return {
            "platform": self.config.platform_id,
            "circuit_state": self.breaker.state.value,
            "tokens_available": round(self.bucket.available, 2),
            "dlq_size": len(self.dlq),
        }
