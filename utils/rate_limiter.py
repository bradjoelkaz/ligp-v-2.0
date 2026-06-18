"""Redis-backed distributed TokenBucket.

Atomic token consumption via a Lua script. Falls back to an in-process
TokenBucket when Redis is unavailable (so it works offline and in tests).
"""

from __future__ import annotations

import threading
import time

_LUA_ACQUIRE = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])

local data = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens = tonumber(data[1])
local last_refill = tonumber(data[2])

if tokens == nil then
    tokens = capacity
    last_refill = now
end

local elapsed = math.max(0, now - last_refill)
tokens = math.min(capacity, tokens + elapsed * refill_rate)

if tokens >= requested then
    tokens = tokens - requested
    redis.call('HMSET', key, 'tokens', tokens, 'last_refill', now)
    redis.call('EXPIRE', key, 3600)
    return 1
else
    redis.call('HMSET', key, 'tokens', tokens, 'last_refill', now)
    redis.call('EXPIRE', key, 3600)
    return 0
end
"""


class _InMemoryTokenBucket:
    """In-process token bucket used when Redis is unavailable."""

    def __init__(self, capacity: float, refill_rate: float) -> None:
        self._capacity = capacity
        self._refill_rate = refill_rate
        self._tokens = capacity
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, tokens: float = 1.0) -> bool:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            self._tokens = min(self._capacity, self._tokens + elapsed * self._refill_rate)
            self._last = now
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def wait_time(self) -> float:
        with self._lock:
            if self._tokens >= 1.0:
                return 0.0
            needed = 1.0 - self._tokens
            return needed / self._refill_rate


class DistributedTokenBucket:
    """Redis-based distributed token bucket with in-memory fallback."""

    def __init__(
        self,
        redis_url: str,
        key: str,
        capacity: float,
        refill_rate: float,
    ) -> None:
        self._key = key
        self._capacity = capacity
        self._refill_rate = refill_rate
        self._fallback = _InMemoryTokenBucket(capacity, refill_rate)
        self._redis_client: object | None = None
        self._script: object | None = None
        self._redis_url = redis_url

    def _get_redis(self) -> object | None:
        if self._redis_client is not None:
            return self._redis_client
        try:
            import redis  # lazy

            client = redis.from_url(self._redis_url)
            client.ping()
            self._redis_client = client
            self._script = client.register_script(_LUA_ACQUIRE)
            return self._redis_client
        except Exception:
            return None

    def acquire(self, tokens: float = 1.0) -> bool:
        """Try to consume tokens. True on success, False when exhausted."""
        r = self._get_redis()
        if r is None or self._script is None:
            return self._fallback.acquire(tokens)
        try:
            result = self._script(  # type: ignore[operator]
                keys=[self._key],
                args=[self._capacity, self._refill_rate, time.time(), tokens],
            )
            return bool(result)
        except Exception:
            return self._fallback.acquire(tokens)

    def wait_time(self) -> float:
        """Estimated seconds until the next token is available."""
        return max(0.0, 1.0 / self._refill_rate)
