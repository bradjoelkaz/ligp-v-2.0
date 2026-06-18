"""Event matching + boost (DD-007).

Matches a node/content item against active events by tag Jaccard overlap
(>= 0.30) or by WikiData QID equality, then aggregates a boost multiplier in
[1.0, 3.0].
"""

from __future__ import annotations

from typing import Any

from utils.helpers import clamp
from utils.logger import get_logger

_log = get_logger(__name__)

_JACCARD_MIN = 0.30
_BOOST_MIN = 1.0
_BOOST_MAX = 3.0


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


class EventMatcher:
    """Match nodes to events and compute the event boost."""

    def __init__(self, jaccard_min: float = _JACCARD_MIN) -> None:
        self.jaccard_min = jaccard_min

    def match(
        self, node: dict[str, Any], active_events: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Return events that match the node by tag overlap or QID."""
        node_tags = set(node.get("tags", []))
        node_qids = set(node.get("qids", []))
        if node.get("qid"):
            node_qids.add(node["qid"])

        matched: list[dict[str, Any]] = []
        for event in active_events:
            event_tags = set(event.get("tags", []))
            jac = _jaccard(node_tags, event_tags)
            qid_hit = bool(node_qids & event_tags) or bool(node_qids & set(event.get("qids", [])))
            if jac >= self.jaccard_min or qid_hit:
                matched.append({**event, "match_score": max(jac, 1.0 if qid_hit else 0.0)})
        return matched

    def compute_event_boost(self, matched_events: list[dict[str, Any]]) -> float:
        """Aggregate boost from matched events, clamped to [1.0, 3.0].

        With no matches the boost is the neutral 1.0. Multiple matches compound
        additively above the 1.0 baseline.
        """
        if not matched_events:
            return _BOOST_MIN
        extra = sum(max(0.0, float(e.get("boost_multiplier", 1.0)) - 1.0) for e in matched_events)
        return clamp(_BOOST_MIN + extra, _BOOST_MIN, _BOOST_MAX)
