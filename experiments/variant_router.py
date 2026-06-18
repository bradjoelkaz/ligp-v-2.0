"""Variant routing (Layer 12).

Routes execution to the variant assigned by :class:`ABTestManager`. ``wrap``
returns a callable that dispatches to ``func_a``/``func_b`` based on the unit's
assignment (variant name ``"A"`` -> func_a, otherwise func_b).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from experiments.ab_test_manager import ABTestManager
from utils.logger import get_logger

_log = get_logger(__name__)


class VariantRouter:
    """Dispatch logic by experiment variant assignment."""

    def __init__(self, manager: ABTestManager) -> None:
        self.manager = manager
        self._handlers: dict[tuple[str, str], Callable[..., Any]] = {}

    def register(self, experiment_id: str, variant: str, handler: Callable[..., Any]) -> None:
        self._handlers[(experiment_id, variant)] = handler

    def route(self, experiment_id: str, unit_id: str) -> Callable[..., Any]:
        """Return the handler registered for this unit's assigned variant."""
        variant = self.manager.assign_variant(experiment_id, unit_id)
        handler = self._handlers.get((experiment_id, variant))
        if handler is None:
            raise KeyError(f"no handler for variant {variant} in {experiment_id}")
        return handler

    def wrap(
        self,
        func_a: Callable[..., Any],
        func_b: Callable[..., Any],
        experiment_id: str,
        unit_id: str,
    ) -> Callable[..., Any]:
        """Return func_a if the unit is assigned variant 'A', else func_b."""
        variant = self.manager.assign_variant(experiment_id, unit_id)
        return func_a if variant == "A" else func_b
