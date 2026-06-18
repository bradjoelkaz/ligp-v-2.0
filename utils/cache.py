"""Redis TTL cache.

Namespaces and TTLs:
  embedding:{node_id}     7 days
  graph_score:{node_id}   1 hour
  naver:{query_hash}      10 minutes
  youtube:{query_hash}    30 minutes
  ctr:{platform}          24 hours

Degrades gracefully to a no-op when Redis is unavailable.
"""

from __future__ import annotations

import hashlib

from utils.logger import get_logger

logger = get_logger(__name__)

_TTL_MAP: dict[str, int] = {
    "embedding": 7 * 24 * 3600,
    "graph_score": 3600,
    "naver": 600,
    "youtube": 1800,
    "ctr": 86400,
}


def cache_key(namespace: str, *args: object) -> str:
    """Deterministic cache key for a namespace + args."""
    payload = ":".join(str(a) for a in args)
    digest = hashlib.md5(payload.encode()).hexdigest()[:12]
    return f"iigp:{namespace}:{digest}"


def default_ttl(namespace: str) -> int:
    return _TTL_MAP.get(namespace, 300)


class RedisCache:
    """Redis TTL cache client (no-op when Redis is down)."""

    def __init__(self, redis_url: str) -> None:
        self._url = redis_url
        self._client: object | None = None

    def _get_client(self) -> object | None:
        if self._client is not None:
            return self._client
        try:
            import redis  # lazy

            client = redis.from_url(self._url)
            client.ping()
            self._client = client
            return client
        except Exception:
            return None

    def get(self, key: str) -> dict | None:
        r = self._get_client()
        if r is None:
            return None
        try:
            import orjson  # lazy

            raw = r.get(key)  # type: ignore[attr-defined]
            return orjson.loads(raw) if raw else None
        except Exception as exc:
            logger.debug("cache_get_failed", extra={"key": key, "error": str(exc)})
            return None

    def set(self, key: str, value: dict, ttl_seconds: int | None = None) -> None:
        r = self._get_client()
        if r is None:
            return
        try:
            import orjson  # lazy

            ns = key.split(":")[1] if ":" in key else "default"
            ttl = ttl_seconds or default_ttl(ns)
            r.setex(key, ttl, orjson.dumps(value))  # type: ignore[attr-defined]
        except Exception as exc:
            logger.debug("cache_set_failed", extra={"key": key, "error": str(exc)})

    def delete(self, key: str) -> None:
        r = self._get_client()
        if r is None:
            return
        try:
            r.delete(key)  # type: ignore[attr-defined]
        except Exception:
            pass

    def exists(self, key: str) -> bool:
        r = self._get_client()
        if r is None:
            return False
        try:
            return bool(r.exists(key))  # type: ignore[attr-defined]
        except Exception:
            return False
