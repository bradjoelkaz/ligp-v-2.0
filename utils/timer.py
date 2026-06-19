"""Timing helpers for latency/SLA tracking (utils/timer.py)."""

from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import ContextDecorator

from utils.logger import get_logger

_log = get_logger(__name__)


class Timer(ContextDecorator):
    """Context manager / decorator that records wall-clock elapsed seconds.

    Example:
        with Timer("graph_score") as t:
            ...
        print(t.elapsed)
    """

    def __init__(self, label: str = "block", on_finish: Callable[[str, float], None] | None = None):
        self.label = label
        self.on_finish = on_finish
        self.elapsed: float = 0.0
        self._start: float = 0.0

    def __enter__(self) -> Timer:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc: object) -> bool:
        self.elapsed = time.perf_counter() - self._start
        if self.on_finish:
            self.on_finish(self.label, self.elapsed)
        else:
            _log.debug("timer", extra={"label": self.label, "elapsed_sec": round(self.elapsed, 6)})
        return False
