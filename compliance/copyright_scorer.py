"""Copyright risk scoring (QA-023).

Produces a risk score in [0.0, 1.0] (0 = safe, 1 = high risk) from three
signals: proportion of directly quoted text, whether a source is attributed,
and the license tag. ``is_safe`` compares against a threshold (default 0.30,
matching the toxicity/risk convention in thresholds.yaml).
"""

from __future__ import annotations

import re
from typing import Any

from utils.helpers import clamp
from utils.logger import get_logger

_log = get_logger(__name__)

_QUOTE_RE = re.compile(r"[\"“”]([^\"“”]{10,})[\"“”]")

# License tags and their inherent risk contribution.
_LICENSE_RISK = {
    "cc0": 0.0,
    "cc-by": 0.05,
    "cc-by-sa": 0.10,
    "public-domain": 0.0,
    "mit": 0.0,
    "fair-use": 0.30,
    "all-rights-reserved": 0.60,
    None: 0.40,
    "": 0.40,
}

# Weighting of each signal (sums to 1.0).
_W_QUOTE = 0.5
_W_ATTRIBUTION = 0.2
_W_LICENSE = 0.3


class CopyrightScorer:
    """Heuristic copyright-risk estimator."""

    def _quote_ratio(self, text: str) -> float:
        if not text:
            return 0.0
        quoted_chars = sum(len(m.group(1)) for m in _QUOTE_RE.finditer(text))
        return clamp(quoted_chars / len(text), 0.0, 1.0)

    def score(self, text: str, source_url: str, license_tag: str | None) -> float:
        """Return a copyright-risk score in [0.0, 1.0]."""
        quote_ratio = self._quote_ratio(text)
        attribution_risk = 0.0 if source_url else 1.0
        license_risk = _LICENSE_RISK.get((license_tag or "").lower() or None, 0.40)
        risk = (
            _W_QUOTE * quote_ratio + _W_ATTRIBUTION * attribution_risk + _W_LICENSE * license_risk
        )
        return clamp(risk, 0.0, 1.0)

    def is_safe(self, score: float, threshold: float = 0.30) -> bool:
        """True when the risk score is at or below the threshold."""
        return score <= threshold

    def assess(self, text: str, source_url: str, license_tag: str | None) -> dict[str, Any]:
        """Convenience: return score + safety verdict."""
        s = self.score(text, source_url, license_tag)
        return {"score": s, "safe": self.is_safe(s)}
