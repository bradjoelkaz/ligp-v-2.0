"""Daily pipeline flow (Layer 15).

``run_daily_pipeline`` is a dependency-light, offline-capable orchestration of
the full IIGP flow (ingest -> dedup -> NLP -> graph -> score -> select ->
generate -> quality gate). It is wrapped by a Prefect ``@flow`` when Prefect is
available; otherwise it runs as a plain function (and is what the integration
test drives).
"""

from __future__ import annotations

from typing import Any

from content_factory.generators.blog_generator import BlogGenerator
from content_factory.quality_gate import QualityGate
from decision_engine.selector import ThompsonSelector
from graph.graph_store import Edge, InMemoryGraphStore, Node
from ingestion.bootstrap_pipeline import bootstrap
from nlp.entity_extractor import EntityExtractor
from processing.deduplicator import Deduplicator
from processing.language_detector import detect_language
from scoring_engine.graph_score import GraphScoreComputer
from scoring_engine.revenue_model import RevenueModel
from utils.helpers import make_node_id
from utils.logger import get_logger

_log = get_logger(__name__)


def run_daily_pipeline(
    documents: list[dict[str, Any]],
    platform: str = "blog",
    top_k: int = 5,
) -> dict[str, Any]:
    """Run the end-to-end pipeline over collected ``documents``.

    Each document is a dict with at least ``title`` and ``text``. Returns a
    summary with the generated/quality-checked content items.
    """
    # 1. Deduplicate.
    dedup = Deduplicator()
    unique: list[dict[str, Any]] = []
    for i, doc in enumerate(documents):
        key = doc.get("source_id", f"doc{i}")
        text = f"{doc.get('title', '')} {doc.get('text', '')}"
        if not dedup.is_duplicate(key, text):
            unique.append(doc)

    # 2. NLP + 3. graph build (seeded for cold start).
    store = bootstrap(InMemoryGraphStore())
    extractor = EntityExtractor()
    for doc in unique:
        text = f"{doc.get('title', '')} {doc.get('text', '')}"
        lang = detect_language(text)
        topic_name = doc.get("title", "untitled")
        topic_id = make_node_id("topic", topic_name)
        store.add_node(Node(id=topic_id, type="topic", name=topic_name, weight=1.0))
        for ent in extractor.extract(text, lang):
            ent_id = ent.qid or make_node_id("entity", ent.text)
            store.add_node(Node(id=ent_id, type="entity", name=ent.text, weight=ent.confidence))
            store.add_edge(Edge(topic_id, ent_id, "related_to", 0.5))

    # 4. Centrality + 5. scoring.
    centrality = store.compute_centrality()
    gsc = GraphScoreComputer()
    revenue = RevenueModel()
    candidates: list[dict[str, Any]] = []
    for node_id, cent in centrality.items():
        node = store.get_node(node_id)
        if node is None or node.type != "topic":
            continue
        candidates.append(
            {
                "node_id": node_id,
                "name": node.name,
                "topic": node_id,
                "edge_sum": len(store.get_neighbors(node_id)),
                "centrality": cent,
                "trend_score": 0.5,
                "event_boost": 0.0,
            }
        )
    gsc.batch_compute(candidates)
    for cand in candidates:
        cand["final_score"] = cand["score"]
        cand["revenue_score"] = revenue.compute(cand["node_id"], platform, "surprise", [])

    # 6. Selection.
    selected = ThompsonSelector().select(candidates, platform, top_k)

    # 7. Generation + quality gate.
    generator = BlogGenerator()
    gate = QualityGate()
    outputs: list[dict[str, Any]] = []
    for cand in selected:
        content = generator.generate({"id": cand["node_id"], "name": cand["name"]}, platform)
        passed, issues = gate.check(content, platform)
        content["quality_passed"] = passed
        content["quality_issues"] = issues
        outputs.append(content)

    summary = {
        "ingested": len(documents),
        "unique": len(unique),
        "graph_nodes": store.num_nodes(),
        "candidates": len(candidates),
        "selected": len(selected),
        "generated": outputs,
    }
    _log.info(
        "daily_pipeline_complete",
        extra={k: summary[k] for k in ("ingested", "unique", "graph_nodes", "selected")},
    )
    return summary


def daily_pipeline() -> dict[str, Any]:  # pragma: no cover - requires prefect + collectors
    """Prefect flow wrapper. Collects live data, then runs the pipeline."""
    try:
        from prefect import flow

        @flow(name="iigp-daily-pipeline")
        def _flow() -> dict[str, Any]:
            return run_daily_pipeline(_collect_live())

        return _flow()
    except Exception:
        return run_daily_pipeline(_collect_live())


def _collect_live() -> list[dict[str, Any]]:  # pragma: no cover - network
    """Placeholder live collection; wired to real collectors in production."""
    return []
