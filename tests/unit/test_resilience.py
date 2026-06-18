"""Tests for circuit breaker, token bucket, DLQ, retry backoff (DD-003)."""

from __future__ import annotations

import asyncio

import pytest

from ingestion.base_collector import (
    BaseCollector,
    CircuitBreaker,
    CircuitState,
    CollectorConfig,
    DeadLetterQueue,
    TokenBucket,
)
from utils.retry import compute_delay


@pytest.mark.unit
def test_circuit_breaker_opens_after_threshold():
    cb = CircuitBreaker(failure_threshold=3, reset_timeout=60)
    assert cb.allow()
    for _ in range(3):
        cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert not cb.allow()


@pytest.mark.unit
def test_circuit_breaker_half_opens_after_timeout():
    cb = CircuitBreaker(failure_threshold=1, reset_timeout=0.0)
    cb.record_failure()
    # reset_timeout=0 -> immediately eligible for HALF_OPEN
    assert cb.state == CircuitState.HALF_OPEN
    cb.record_success()
    assert cb.state == CircuitState.CLOSED


@pytest.mark.unit
def test_token_bucket_consumes_and_exhausts():
    tb = TokenBucket(capacity=3, window_sec=10_000)
    assert tb.consume()
    assert tb.consume()
    assert tb.consume()
    assert not tb.consume()  # exhausted


@pytest.mark.unit
def test_token_bucket_rejects_invalid_capacity():
    with pytest.raises(ValueError):
        TokenBucket(capacity=0)


@pytest.mark.unit
def test_dead_letter_queue_push_and_drain():
    dlq = DeadLetterQueue()
    dlq.push({"a": 1}, error="boom")
    assert len(dlq) == 1
    drained = dlq.drain()
    assert drained[0]["error"] == "boom"
    assert len(dlq) == 0


@pytest.mark.unit
@pytest.mark.parametrize(
    "strategy,attempt,expected_ceiling",
    [("exponential", 3, 8.0), ("linear", 3, 6.0), ("fibonacci", 5, 10.0)],
)
def test_compute_delay_respects_strategy(strategy, attempt, expected_ceiling):
    delay = compute_delay(attempt, strategy=strategy, base=2.0, jitter=False)
    assert delay == pytest.approx(expected_ceiling)


@pytest.mark.unit
def test_compute_delay_caps_at_max():
    assert compute_delay(20, strategy="exponential", base=2.0, max_delay=30.0, jitter=False) == 30.0


class _FlakyCollector(BaseCollector):
    def __init__(self, fail_times: int):
        super().__init__(CollectorConfig(platform_id="test", max_retries=5, failure_threshold=10))
        self.fail_times = fail_times
        self.calls = 0

    async def fetch(self, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("transient")
        return [{"ok": True}]


@pytest.mark.unit
def test_collector_recovers_after_transient_failures():
    c = _FlakyCollector(fail_times=2)
    # patch sleep to avoid real backoff delays
    import ingestion.base_collector as mod

    async def _no_sleep(_):
        return None

    orig = mod.asyncio.sleep
    mod.asyncio.sleep = _no_sleep  # type: ignore
    try:
        items = asyncio.run(c.collect())
    finally:
        mod.asyncio.sleep = orig  # type: ignore
    assert items == [{"ok": True}]
    assert len(c.dlq) == 0


@pytest.mark.unit
def test_collector_routes_to_dlq_after_exhaustion():
    c = _FlakyCollector(fail_times=99)

    import ingestion.base_collector as mod

    async def _no_sleep(_):
        return None

    orig = mod.asyncio.sleep
    mod.asyncio.sleep = _no_sleep  # type: ignore
    try:
        items = asyncio.run(c.collect())
    finally:
        mod.asyncio.sleep = orig  # type: ignore
    assert items == []
    assert len(c.dlq) == 1


@pytest.mark.unit
def test_collector_config_from_platform():
    platform = {
        "platform_id": "rss",
        "api_quota_per_day": 100000,
        "backoff_strategy": "linear",
        "circuit_breaker": {"failure_threshold": 7},
    }
    defaults = {
        "quota_window_sec": 86400,
        "backoff_base_sec": 2,
        "circuit_breaker": {"reset_timeout_sec": 60},
    }
    cfg = CollectorConfig.from_platform(platform, defaults)
    assert cfg.platform_id == "rss"
    assert cfg.backoff_strategy == "linear"
    assert cfg.failure_threshold == 7
    assert cfg.reset_timeout_sec == 60
