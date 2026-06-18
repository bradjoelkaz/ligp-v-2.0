"""Retry / backoff helpers (utils/retry.py).

Implements exponential / linear / fibonacci backoff with optional jitter,
matching the ``backoff_strategy`` field in ``config/platforms.yaml`` (DD-001).
Pure stdlib so it is testable without external retry libraries.
"""

from __future__ import annotations

import asyncio
import functools
import random
import time
from collections.abc import Callable, Iterable
from typing import TypeVar

from utils.logger import get_logger

_log = get_logger(__name__)
T = TypeVar("T")


def compute_delay(
    attempt: int,
    *,
    strategy: str = "exponential",
    base: float = 2.0,
    max_delay: float = 300.0,
    jitter: bool = True,
) -> float:
    """Return the backoff delay (seconds) for a 1-indexed ``attempt``."""
    if attempt < 1:
        attempt = 1
    if strategy == "linear":
        delay = base * attempt
    elif strategy == "fibonacci":
        a, b = 1, 1
        for _ in range(attempt - 1):
            a, b = b, a + b
        delay = base * a
    else:  # exponential (default)
        delay = base * (2 ** (attempt - 1))
    delay = min(delay, max_delay)
    if jitter:
        delay = random.uniform(0, delay)  # full jitter
    return delay


def retry(
    *,
    max_attempts: int = 5,
    strategy: str = "exponential",
    base: float = 2.0,
    max_delay: float = 300.0,
    jitter: bool = True,
    exceptions: Iterable[type[BaseException]] = (Exception,),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator adding retry-with-backoff to sync or async callables."""
    exc_tuple = tuple(exceptions)

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        if asyncio.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: object, **kwargs: object) -> T:
                last: BaseException | None = None
                for attempt in range(1, max_attempts + 1):
                    try:
                        return await func(*args, **kwargs)  # type: ignore[misc]
                    except exc_tuple as exc:
                        last = exc
                        if attempt == max_attempts:
                            break
                        delay = compute_delay(
                            attempt,
                            strategy=strategy,
                            base=base,
                            max_delay=max_delay,
                            jitter=jitter,
                        )
                        _log.warning(
                            "retry",
                            extra={
                                "func": func.__name__,
                                "attempt": attempt,
                                "delay_sec": round(delay, 3),
                            },
                        )
                        await asyncio.sleep(delay)
                assert last is not None
                raise last

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(func)
        def sync_wrapper(*args: object, **kwargs: object) -> T:
            last: BaseException | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exc_tuple as exc:
                    last = exc
                    if attempt == max_attempts:
                        break
                    delay = compute_delay(
                        attempt, strategy=strategy, base=base, max_delay=max_delay, jitter=jitter
                    )
                    _log.warning(
                        "retry",
                        extra={
                            "func": func.__name__,
                            "attempt": attempt,
                            "delay_sec": round(delay, 3),
                        },
                    )
                    time.sleep(delay)
            assert last is not None
            raise last

        return sync_wrapper

    return decorator
