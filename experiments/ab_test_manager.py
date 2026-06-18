"""A/B test manager (QA-031).

Manages experiments with deterministic, hash-based variant assignment so the
same unit always lands in the same variant. Records per-variant outcomes and
computes results (means + significance via StatisticalTester).
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from experiments.statistical_significance import StatisticalTester
from utils.helpers import utcnow_iso
from utils.logger import get_logger

_log = get_logger(__name__)


class ABTestManager:
    """Create experiments, assign variants, record outcomes, compute results."""

    def __init__(self) -> None:
        self._experiments: dict[str, dict[str, Any]] = {}
        self._outcomes: dict[str, dict[str, list[float]]] = {}
        self._tester = StatisticalTester()

    def create_experiment(self, name: str, variants: list[str], traffic_split: list[float]) -> str:
        """Register an experiment; traffic_split must sum to 1.0."""
        if len(variants) != len(traffic_split):
            raise ValueError("variants and traffic_split must align")
        if abs(sum(traffic_split) - 1.0) > 1e-6:
            raise ValueError("traffic_split must sum to 1.0")
        if len(variants) < 2:
            raise ValueError("need at least two variants")
        exp_id = str(uuid.uuid4())
        self._experiments[exp_id] = {
            "experiment_id": exp_id,
            "name": name,
            "variants": list(variants),
            "traffic_split": list(traffic_split),
            "status": "running",
            "created_at": utcnow_iso(),
        }
        self._outcomes[exp_id] = {v: [] for v in variants}
        return exp_id

    @staticmethod
    def _hash_unit(experiment_id: str, unit_id: str) -> float:
        digest = hashlib.sha256(f"{experiment_id}:{unit_id}".encode()).digest()
        return int.from_bytes(digest[:8], "big") / float(1 << 64)

    def assign_variant(self, experiment_id: str, unit_id: str) -> str:
        """Deterministically map a unit to a variant by cumulative split."""
        exp = self._experiments.get(experiment_id)
        if exp is None:
            raise KeyError(f"unknown experiment: {experiment_id}")
        bucket = self._hash_unit(experiment_id, unit_id)
        cumulative = 0.0
        for variant, share in zip(exp["variants"], exp["traffic_split"], strict=True):
            cumulative += share
            if bucket < cumulative:
                return variant
        return exp["variants"][-1]

    def record_outcome(self, experiment_id: str, variant: str, metric: float) -> None:
        if experiment_id not in self._outcomes:
            raise KeyError(f"unknown experiment: {experiment_id}")
        if variant not in self._outcomes[experiment_id]:
            raise ValueError(f"unknown variant: {variant}")
        self._outcomes[experiment_id][variant].append(float(metric))

    def get_results(self, experiment_id: str) -> dict[str, Any]:
        """Return per-variant means and a two-variant significance verdict."""
        exp = self._experiments.get(experiment_id)
        if exp is None:
            raise KeyError(f"unknown experiment: {experiment_id}")
        outcomes = self._outcomes[experiment_id]
        means = {v: (sum(vals) / len(vals) if vals else 0.0) for v, vals in outcomes.items()}
        result: dict[str, Any] = {
            "experiment_id": experiment_id,
            "means": means,
            "counts": {v: len(vals) for v, vals in outcomes.items()},
            "p_value": None,
            "significant": False,
            "winner": None,
        }
        variants = exp["variants"]
        if len(variants) == 2:
            a, b = variants
            test = self._tester.test(outcomes[a], outcomes[b])
            result["p_value"] = test["p_value"]
            result["significant"] = test["significant"]
            if test["significant"]:
                result["winner"] = a if means[a] >= means[b] else b
        else:
            result["winner"] = max(means, key=lambda k: means[k]) if any(means.values()) else None
        return result
