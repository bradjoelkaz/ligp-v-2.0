"""Distributed TokenBucket + cache key tests (no Redis required)."""

from __future__ import annotations

import pytest

from utils.cache import cache_key, default_ttl
from utils.rate_limiter import DistributedTokenBucket, _InMemoryTokenBucket


@pytest.mark.unit
def test_inmemory_bucket_acquire_success():
    bucket = _InMemoryTokenBucket(capacity=10.0, refill_rate=1.0)
    assert bucket.acquire(1.0) is True


@pytest.mark.unit
def test_inmemory_bucket_exhaustion():
    bucket = _InMemoryTokenBucket(capacity=2.0, refill_rate=0.01)
    bucket.acquire(2.0)
    assert bucket.acquire(1.0) is False


@pytest.mark.unit
def test_inmemory_wait_time_positive():
    bucket = _InMemoryTokenBucket(capacity=1.0, refill_rate=1.0)
    bucket.acquire(1.0)
    assert bucket.wait_time() > 0.0


@pytest.mark.unit
def test_distributed_bucket_fallback():
    # Unreachable Redis -> in-memory fallback still works.
    bucket = DistributedTokenBucket(
        redis_url="redis://localhost:6390",
        key="test",
        capacity=5.0,
        refill_rate=1.0,
    )
    assert bucket.acquire(1.0) is True
    assert bucket.wait_time() >= 0.0


@pytest.mark.unit
def test_cache_key_deterministic():
    k1 = cache_key("embedding", "node_abc")
    k2 = cache_key("embedding", "node_abc")
    assert k1 == k2
    assert k1.startswith("iigp:embedding:")


@pytest.mark.unit
def test_cache_key_different_inputs():
    assert cache_key("embedding", "node_abc") != cache_key("embedding", "node_xyz")


@pytest.mark.unit
def test_default_ttl_known_and_unknown():
    assert default_ttl("embedding") == 7 * 24 * 3600
    assert default_ttl("graph_score") == 3600
    assert default_ttl("nonexistent") == 300
