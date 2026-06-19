"""Edge construction helpers (Layer 3 / QA-009).

Edge weights are initialized from the per-relation defaults in
``config/weights.yaml -> edge_default_weights`` so there is a single source of
truth for initialization (QA-009).
"""

from __future__ import annotations

from functools import lru_cache

from graph.graph_store import RELATION_TYPES, Edge
from utils.config_loader import load_config
from utils.logger import get_logger

_log = get_logger(__name__)

# Fallback used if weights.yaml is unavailable (mirrors the ERD defaults).
_FALLBACK_DEFAULTS = {
    "related_to": 0.5,
    "causes": 0.8,
    "similar_to": 0.4,
    "leads_to": 0.6,
    "monetizes_via": 0.9,
    "triggers_emotion": 0.7,
    "belongs_to_event": 0.65,
}


@lru_cache(maxsize=1)
def _defaults() -> dict[str, float]:
    try:
        return {**_FALLBACK_DEFAULTS, **load_config("weights").get("edge_default_weights", {})}
    except Exception:  # pragma: no cover - config optional in some tests
        return dict(_FALLBACK_DEFAULTS)


def default_weight(relation_type: str) -> float:
    return _defaults().get(relation_type, 0.5)


def build_edge(
    from_node: str, to_node: str, relation_type: str, weight: float | None = None, **attrs
) -> Edge:
    if relation_type not in RELATION_TYPES:
        raise ValueError(f"invalid relation type: {relation_type}")
    return Edge(
        from_node=from_node,
        to_node=to_node,
        relation_type=relation_type,
        weight=default_weight(relation_type) if weight is None else weight,
        attrs=attrs,
    )
