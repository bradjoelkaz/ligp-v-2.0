"""Bayesian CTR / CVR model (DD-002 / QA-014).

CTR ~ Beta(alpha + clicks, beta + (impressions − clicks)). Priors come from
``weights.yaml -> platform_ctr_prior``. ``sample_ctr`` performs a Thompson
Sampling draw used by the decision engine.
"""

from __future__ import annotations

import random
from functools import lru_cache

from utils.config_loader import load_config
from utils.logger import get_logger

_log = get_logger(__name__)

_FALLBACK_PRIORS: dict[str, dict[str, float]] = {
    "blog": {"alpha": 2.0, "beta": 98.0},
    "youtube": {"alpha": 4.0, "beta": 96.0},
    "instagram": {"alpha": 3.5, "beta": 96.5},
    "newsletter": {"alpha": 5.0, "beta": 95.0},
    "shorts": {"alpha": 4.5, "beta": 95.5},
}
_DEFAULT_PRIOR = {"alpha": 1.0, "beta": 99.0}


@lru_cache(maxsize=1)
def _priors() -> dict[str, dict[str, float]]:
    try:
        cfg = load_config("weights").get("platform_ctr_prior")
        return cfg if cfg else dict(_FALLBACK_PRIORS)
    except Exception:  # pragma: no cover
        return dict(_FALLBACK_PRIORS)


class ProbabilityModel:
    """Per-platform Beta posteriors with online updates and Thompson sampling."""

    def __init__(self, rng: random.Random | None = None) -> None:
        priors = _priors()
        self._posterior: dict[str, dict[str, float]] = {
            p: {"alpha": float(v["alpha"]), "beta": float(v["beta"])} for p, v in priors.items()
        }
        self._rng = rng or random.Random()

    def _params(self, platform: str) -> dict[str, float]:
        if platform not in self._posterior:
            self._posterior[platform] = dict(_DEFAULT_PRIOR)
        return self._posterior[platform]

    def update_ctr(self, platform: str, clicks: int, impressions: int) -> None:
        """Online Bayesian update of the platform's CTR posterior."""
        if clicks < 0 or impressions < 0 or clicks > impressions:
            raise ValueError("require 0 <= clicks <= impressions")
        params = self._params(platform)
        params["alpha"] += clicks
        params["beta"] += impressions - clicks
        _log.debug("ctr_updated", extra={"platform": platform, **params})

    def sample_ctr(self, platform: str) -> float:
        """Draw a Thompson sample from the platform's posterior (in [0, 1])."""
        params = self._params(platform)
        return self._rng.betavariate(params["alpha"], params["beta"])

    def get_ctr_estimate(self, platform: str) -> tuple[float, float]:
        """Return (mean, variance) of the platform's CTR posterior."""
        params = self._params(platform)
        a, b = params["alpha"], params["beta"]
        total = a + b
        mean = a / total
        variance = (a * b) / (total * total * (total + 1.0))
        return mean, variance
