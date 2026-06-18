"""Adaptive weight updater (QA-025).

Online gradient update of scoring weights:
    w_new = clip(w_old + lr * (actual - expected) * gradient, [w_min, w_max])

Learning rate and bounds come from ``weights.yaml -> learning_rate`` and
``weight_bounds``. Updated weights are held in memory and can be flushed back to
a YAML file (PyYAML lazy).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from utils.config_loader import load_config
from utils.helpers import clamp
from utils.logger import get_logger

_log = get_logger(__name__)

_FALLBACK_LR = {"initial": 0.01, "min": 0.0001}
_FALLBACK_BOUNDS = {"min": 0.01, "max": 10.0, "gradient_clip": 1.0}


@lru_cache(maxsize=1)
def _lr_config() -> dict[str, Any]:
    try:
        return {**_FALLBACK_LR, **(load_config("weights").get("learning_rate") or {})}
    except Exception:  # pragma: no cover
        return dict(_FALLBACK_LR)


@lru_cache(maxsize=1)
def _bounds_config() -> dict[str, Any]:
    try:
        return {**_FALLBACK_BOUNDS, **(load_config("weights").get("weight_bounds") or {})}
    except Exception:  # pragma: no cover
        return dict(_FALLBACK_BOUNDS)


class WeightUpdater:
    """Stateful adaptive updater for named scoring weights."""

    def __init__(self, initial_weights: dict[str, float] | None = None) -> None:
        lr = _lr_config()
        bounds = _bounds_config()
        self.lr = float(lr.get("initial", 0.01))
        self.w_min = float(bounds.get("min", 0.01))
        self.w_max = float(bounds.get("max", 10.0))
        self.grad_clip = float(bounds.get("gradient_clip", 1.0))
        self.weights: dict[str, float] = dict(initial_weights or {})

    def apply_bounds(self, weight: float) -> float:
        """Clamp a weight into the configured [min, max] range."""
        return clamp(weight, self.w_min, self.w_max)

    def update(
        self, component: str, actual: float, expected: float, gradient: float = 1.0
    ) -> float:
        """Update one component's weight from a prediction error and return it."""
        old = self.weights.get(component, 1.0)
        error = actual - expected
        grad = clamp(gradient, -self.grad_clip, self.grad_clip)
        new = self.apply_bounds(old + self.lr * error * grad)
        self.weights[component] = new
        _log.debug(
            "weight_update",
            extra={"component": component, "old": old, "new": new, "error": error},
        )
        return new

    def flush_to_yaml(self, path: str) -> None:
        """Persist current weights to a YAML file (PyYAML lazy)."""
        try:  # pragma: no cover - requires PyYAML + filesystem
            import yaml

            with open(path, "w", encoding="utf-8") as fh:
                yaml.safe_dump({"updated_weights": self.weights}, fh, allow_unicode=True)
            _log.info("weights_flushed", extra={"path": path, "count": len(self.weights)})
        except Exception as exc:  # pragma: no cover
            _log.warning("weight_flush_failed", extra={"path": path, "error": str(exc)})
