"""Tests for graph propagation, versioning, query, and seasonality (Phase 2)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from graph.graph_store import Edge, InMemoryGraphStore, Node
from graph.propagation import GraphPropagation
from graph.query import GraphQuery
from graph.versioning import GraphVersioning
from time_engine.seasonality import SeasonalityDetector


def _graph():
    g = InMemoryGraphStore()
    for nid in ["topic:a", "topic:b", "topic:c", "topic:d"]:
        g.add_node(Node(id=nid, type="topic", name=nid))
    g.add_edge(Edge("topic:a", "topic:b", "related_to", 0.8))
    g.add_edge(Edge("topic:b", "topic:c", "related_to", 0.5))
    g.add_edge(Edge("topic:a", "topic:d", "causes", 0.9))
    return g


@pytest.mark.unit
def test_propagation_reaches_two_hops():
    g = _graph()
    prop = GraphPropagation(hop_decay=0.5)
    scores = prop.propagate(g, "topic:a", hops=2)
    assert "topic:b" in scores and "topic:d" in scores
    assert "topic:c" in scores  # reached at hop 2 via b
    assert "topic:a" not in scores  # source excluded


@pytest.mark.unit
def test_propagation_unknown_node_raises():
    g = _graph()
    with pytest.raises(KeyError):
        GraphPropagation().propagate(g, "topic:missing")


@pytest.mark.unit
def test_propagation_invalid_decay():
    with pytest.raises(ValueError):
        GraphPropagation(hop_decay=0.0)


@pytest.mark.unit
def test_versioning_snapshot_and_diff():
    g = _graph()
    ver = GraphVersioning(keep_versions=7)
    s1 = ver.create_snapshot(g, "initial")
    g.add_node(Node(id="topic:e", type="topic", name="e"))
    g.add_edge(Edge("topic:a", "topic:e", "related_to", 0.4))
    s2 = ver.create_snapshot(g, "after_add")
    d = ver.diff(s1, s2)
    assert "topic:e" in d["added_nodes"]
    assert any("topic:e" in e for e in d["added_edges"])
    assert len(ver.list_snapshots()) == 2


@pytest.mark.unit
def test_versioning_rollback_restores_state():
    g = _graph()
    ver = GraphVersioning()
    s1 = ver.create_snapshot(g, "initial")
    nodes_before = g.num_nodes()
    g.add_node(Node(id="topic:z", type="topic", name="z"))
    assert g.num_nodes() == nodes_before + 1
    ver.rollback(g, s1)
    assert g.num_nodes() == nodes_before


@pytest.mark.unit
def test_versioning_keeps_only_n_versions():
    g = _graph()
    ver = GraphVersioning(keep_versions=3)
    for i in range(5):
        ver.create_snapshot(g, f"snap{i}")
    assert len(ver.list_snapshots()) == 3


@pytest.mark.unit
def test_query_neighbors_and_relation_filter():
    g = _graph()
    q = GraphQuery(g)
    all_n = q.get_neighbors("topic:a", max_hops=1)
    assert {n["node_id"] for n in all_n} == {"topic:b", "topic:d"}
    only_causes = q.get_neighbors("topic:a", relation="causes", max_hops=1)
    assert [n["node_id"] for n in only_causes] == ["topic:d"]


@pytest.mark.unit
def test_query_shortest_path():
    g = _graph()
    q = GraphQuery(g)
    path = q.shortest_path("topic:a", "topic:c")
    assert path[0] == "topic:a" and path[-1] == "topic:c"


@pytest.mark.unit
def test_query_subgraph():
    g = _graph()
    q = GraphQuery(g)
    sub = q.subgraph(["topic:a", "topic:b"], include_edges=True)
    assert len(sub["nodes"]) == 2
    assert any(e["to_node"] == "topic:b" for e in sub["edges"])


@pytest.mark.unit
def test_query_top_k_by_score():
    g = InMemoryGraphStore()
    g.add_node(Node(id="t:1", type="topic", name="1", weight=0.9))
    g.add_node(Node(id="t:2", type="topic", name="2", weight=0.2))
    q = GraphQuery(g)
    top = q.top_k_by_score(k=10, min_score=0.35)
    assert [t["node_id"] for t in top] == ["t:1"]


@pytest.mark.unit
def test_seasonality_boost_within_range():
    sd = SeasonalityDetector()
    start = datetime(2026, 1, 1)
    dates = [start + timedelta(days=i) for i in range(60)]
    values = [10 + (i % 7) for i in range(60)]
    sd.fit(dates, values)
    boost = sd.get_seasonal_boost(start + timedelta(days=61))
    assert 0.5 <= boost <= 2.0


@pytest.mark.unit
def test_seasonality_predict_next_days():
    sd = SeasonalityDetector()
    start = datetime(2026, 1, 1)
    dates = [start + timedelta(days=i) for i in range(30)]
    values = [float(i) for i in range(30)]
    sd.fit(dates, values)
    preds = sd.predict_next_n_days(7)
    assert len(preds) == 7
    assert all("yhat" in p for p in preds)


@pytest.mark.unit
def test_seasonality_requires_fit():
    sd = SeasonalityDetector()
    with pytest.raises(RuntimeError):
        sd.predict_next_n_days(7)
