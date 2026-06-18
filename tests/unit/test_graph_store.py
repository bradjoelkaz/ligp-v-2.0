"""Tests for the GraphStore adapter (DD-006) and bootstrap (QA-004)."""

from __future__ import annotations

import pytest

from graph.edge_builder import build_edge, default_weight
from graph.graph_store import Edge, InMemoryGraphStore, Node, get_graph_store
from graph.node_builder import build_node
from ingestion.bootstrap_pipeline import bootstrap


@pytest.mark.unit
def test_add_node_and_edge_and_neighbors():
    g = InMemoryGraphStore()
    g.add_node(Node(id="topic:ai", type="topic", name="AI"))
    g.add_node(Node(id="entity:openai", type="entity", name="OpenAI"))
    g.add_edge(Edge("topic:ai", "entity:openai", "related_to", 0.5))
    assert g.num_nodes() == 2
    assert g.num_edges() == 1
    assert g.get_neighbors("topic:ai") == ["entity:openai"]


@pytest.mark.unit
def test_edge_requires_existing_endpoints():
    g = InMemoryGraphStore()
    g.add_node(Node(id="topic:ai", type="topic", name="AI"))
    with pytest.raises(KeyError):
        g.add_edge(Edge("topic:ai", "entity:missing", "related_to", 0.5))


@pytest.mark.unit
def test_invalid_node_type_rejected():
    g = InMemoryGraphStore()
    with pytest.raises(ValueError):
        g.add_node(Node(id="x:y", type="not_a_type", name="x"))


@pytest.mark.unit
def test_invalid_relation_type_rejected():
    g = InMemoryGraphStore()
    g.add_node(Node(id="a:1", type="topic", name="a"))
    g.add_node(Node(id="b:1", type="topic", name="b"))
    with pytest.raises(ValueError):
        g.add_edge(Edge("a:1", "b:1", "bogus", 0.5))


@pytest.mark.unit
def test_pagerank_centrality_sums_to_one():
    g = InMemoryGraphStore()
    for i in range(4):
        g.add_node(Node(id=f"topic:{i}", type="topic", name=str(i)))
    g.add_edge(Edge("topic:0", "topic:1", "related_to", 1.0))
    g.add_edge(Edge("topic:1", "topic:2", "related_to", 1.0))
    g.add_edge(Edge("topic:2", "topic:0", "related_to", 1.0))
    g.add_edge(Edge("topic:3", "topic:0", "related_to", 1.0))
    cent = g.compute_centrality()
    assert pytest.approx(sum(cent.values()), abs=1e-6) == 1.0
    # node 0 has the most inbound weight -> highest centrality
    assert cent["topic:0"] == max(cent.values())


@pytest.mark.unit
def test_default_weight_matches_qa009_table():
    assert default_weight("monetizes_via") == 0.9
    assert default_weight("similar_to") == 0.4


@pytest.mark.unit
def test_build_edge_uses_default_weight_when_unspecified():
    e = build_edge("a", "b", "causes")
    assert e.weight == 0.8


@pytest.mark.unit
def test_build_node_makes_deterministic_id():
    n = build_node("topic", "Artificial Intelligence")
    assert n.id == "topic:artificial_intelligence"


@pytest.mark.unit
def test_get_graph_store_inmemory():
    assert isinstance(get_graph_store("inmemory"), InMemoryGraphStore)


@pytest.mark.unit
def test_bootstrap_loads_seed_data():
    g = bootstrap(InMemoryGraphStore())
    assert g.num_nodes() >= 12
    assert g.num_edges() >= 12
    # idempotent: re-running on a populated graph is a no-op
    before = g.num_nodes()
    bootstrap(g)
    assert g.num_nodes() == before
