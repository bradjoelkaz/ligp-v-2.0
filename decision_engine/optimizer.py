"""Markowitz portfolio optimizer (QA-020).

Allocates publishing weight across selected candidates to maximize expected
return for a given risk (covariance), subject to:
    Σ w_i = 1,  w_i >= w_min  (from weights.yaml -> weight_bounds.min)

Uses ``cvxpy`` when available (lazy import). Falls back to an analytic
inverse-variance allocation so the module works offline and is unit-testable.
"""

from __future__ import annotations

from functools import lru_cache

from utils.config_loader import load_config
from utils.logger import get_logger

_log = get_logger(__name__)

_FALLBACK_BOUNDS = {"min": 0.01, "max": 10.0}


@lru_cache(maxsize=1)
def _bounds() -> dict[str, float]:
    try:
        cfg = load_config("weights").get("weight_bounds")
        return cfg if cfg else dict(_FALLBACK_BOUNDS)
    except Exception:  # pragma: no cover
        return dict(_FALLBACK_BOUNDS)


class MarkowitzOptimizer:
    """Mean-variance portfolio weights over content candidates."""

    def __init__(self, risk_aversion: float = 1.0) -> None:
        self.risk_aversion = risk_aversion
        bounds = _bounds()
        self.w_min = float(bounds.get("min", 0.01))

    def optimize(
        self,
        candidates: list[dict],
        expected_returns: list[float],
        cov_matrix: list[list[float]],
    ) -> list[float]:
        """Return portfolio weights summing to 1.0 (each >= w_min)."""
        n = len(expected_returns)
        if n == 0:
            return []
        if len(candidates) != n or len(cov_matrix) != n:
            raise ValueError("candidates, expected_returns and cov_matrix must align")
        if n == 1:
            return [1.0]

        weights = self._optimize_cvxpy(expected_returns, cov_matrix)
        if weights is None:
            weights = self._optimize_fallback(expected_returns, cov_matrix)
        return self._apply_min_and_renormalize(weights)

    def _optimize_cvxpy(
        self, expected_returns: list[float], cov_matrix: list[list[float]]
    ) -> list[float] | None:
        try:  # pragma: no cover - exercised only when cvxpy installed
            import cvxpy as cp
            import numpy as np

            n = len(expected_returns)
            w = cp.Variable(n)
            mu = np.array(expected_returns)
            sigma = np.array(cov_matrix)
            objective = cp.Maximize(
                mu @ w - self.risk_aversion * cp.quad_form(w, cp.psd_wrap(sigma))
            )
            constraints = [cp.sum(w) == 1, w >= self.w_min]
            cp.Problem(objective, constraints).solve()
            if w.value is None:
                return None
            return [float(x) for x in w.value]
        except Exception:
            return None

    def _optimize_fallback(
        self, expected_returns: list[float], cov_matrix: list[list[float]]
    ) -> list[float]:
        """Inverse-variance weighting tilted by expected return."""
        inv: list[float] = []
        for i, ret in enumerate(expected_returns):
            var = cov_matrix[i][i] if cov_matrix[i][i] > 0 else 1e-6
            inv.append(max(ret, 0.0) / var + 1e-9)
        total = sum(inv) or 1.0
        return [v / total for v in inv]

    def _apply_min_and_renormalize(self, weights: list[float]) -> list[float]:
        clamped = [max(self.w_min, w) for w in weights]
        total = sum(clamped) or 1.0
        return [w / total for w in clamped]
