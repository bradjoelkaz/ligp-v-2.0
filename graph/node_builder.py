"""Node construction helpers (Layer 3).

Turns extracted entities / topics into graph ``Node`` objects with stable,
deterministic ids (``utils.helpers.make_node_id``).
"""

from __future__ import annotations

from graph.graph_store import NODE_TYPES, Node
from nlp.entity_extractor import Entity
from utils.helpers import make_node_id


def build_node(node_type: str, name: str, *, weight: float = 1.0, **attrs) -> Node:
    if node_type not in NODE_TYPES:
        raise ValueError(f"invalid node type: {node_type}")
    return Node(
        id=make_node_id(node_type, name),
        type=node_type,
        name=name,
        weight=weight,
        attrs=attrs,
    )


def node_from_entity(entity: Entity) -> Node:
    """Map a NER Entity to an ``entity`` node, carrying QID + confidence."""
    return Node(
        id=entity.qid or make_node_id("entity", entity.text),
        type="entity",
        name=entity.text,
        weight=float(entity.confidence),
        attrs={"qid": entity.qid, "ner_label": entity.label, "language": entity.language},
    )
