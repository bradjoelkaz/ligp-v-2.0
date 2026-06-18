"""Statistical significance testing (QA-031).

Provides Mann-Whitney U, Welch's t-test, and a normal-approximation fallback.
SciPy is used when available (lazy import); otherwise a pure-Python
Mann-Whitney U with a normal approximation is used so the module works offline.
p < 0.05 is considered significant.
"""

from __future__ import annotations

import math
from typing import Any

from utils.logger import get_logger

_log = get_logger(__name__)

_ALPHA = 0.05


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _normal_cdf(z: float) -> float:
    """Standard normal CDF via the error function."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


class StatisticalTester:
    """Compare two samples and report significance."""

    def __init__(self, alpha: float = _ALPHA) -> None:
        self.alpha = alpha

    def test(
        self, control: list[float], treatment: list[float], method: str = "mannwhitney"
    ) -> dict[str, Any]:
        """Return {statistic, p_value, significant, winner}."""
        if len(control) < 2 or len(treatment) < 2:
            return {"statistic": 0.0, "p_value": 1.0, "significant": False, "winner": None}

        scipy_result = self._scipy_test(control, treatment, method)
        if scipy_result is not None:  # pragma: no cover - requires scipy
            stat, p = scipy_result
        else:
            stat, p = self._mannwhitney_normal(control, treatment)

        significant = p < self.alpha
        winner = None
        if significant:
            winner = "treatment" if _mean(treatment) >= _mean(control) else "control"
        return {
            "statistic": float(stat),
            "p_value": float(p),
            "significant": bool(significant),
            "winner": winner,
        }

    def _scipy_test(
        self, control: list[float], treatment: list[float], method: str
    ):  # pragma: no cover - optional dependency
        try:
            from scipy import stats

            if method == "ttest":
                res = stats.ttest_ind(treatment, control, equal_var=False)
                return float(res.statistic), float(res.pvalue)
            res = stats.mannwhitneyu(treatment, control, alternative="two-sided")
            return float(res.statistic), float(res.pvalue)
        except Exception:
            return None

    def _mannwhitney_normal(
        self, control: list[float], treatment: list[float]
    ) -> tuple[float, float]:
        """Mann-Whitney U with a normal approximation (ties ignored)."""
        n1, n2 = len(treatment), len(control)
        combined = [(v, "t") for v in treatment] + [(v, "c") for v in control]
        combined.sort(key=lambda x: x[0])
        # Average ranks (1-indexed) handling ties.
        ranks = [0.0] * len(combined)
        i = 0
        while i < len(combined):
            j = i
            while j + 1 < len(combined) and combined[j + 1][0] == combined[i][0]:
                j += 1
            avg_rank = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                ranks[k] = avg_rank
            i = j + 1
        r1 = sum(rank for rank, (_, grp) in zip(ranks, combined, strict=True) if grp == "t")
        u1 = r1 - n1 * (n1 + 1) / 2.0
        u = min(u1, n1 * n2 - u1)
        mu = n1 * n2 / 2.0
        sigma = math.sqrt(n1 * n2 * (n1 + n2 + 1) / 12.0)
        if sigma == 0:
            return u, 1.0
        z = (u - mu) / sigma
        p = 2.0 * _normal_cdf(z)  # two-sided (z <= 0 since u <= mu)
        return u, min(1.0, max(0.0, p))

    def required_sample_size(self, effect_size: float, power: float = 0.80) -> int:
        """Approximate per-group sample size for a two-sided test (Cohen)."""
        if effect_size <= 0:
            raise ValueError("effect_size must be positive")
        z_alpha = 1.959963985  # z_{0.975}
        z_power = {0.80: 0.8416, 0.90: 1.2816, 0.95: 1.6449}.get(power, 0.8416)
        n = 2.0 * ((z_alpha + z_power) / effect_size) ** 2
        return max(2, math.ceil(n))
