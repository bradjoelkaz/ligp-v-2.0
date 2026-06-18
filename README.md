# IIGP v2.0

> "인터넷 데이터를 그래프로 변환하고, 수익이 흐르는 경로를 계산하는 엔진"
> An engine that turns internet data into a graph and computes the paths where revenue flows.

Graph-centric structure + probability-based decisions + time awareness + feedback learning + revenue optimization.

---

## Status: Phase 0 — Foundation Infrastructure

This repository currently contains the **Phase 0** scaffold only:

- Full 16-layer directory structure (`iigp/` layout mapped to the repo root)
- `.env.example` / `.env` (local placeholder) and `.gitignore`
- `requirements.txt` (pinned lower bounds across all layers)
- `config/` YAML files (validated, see below)
- Cold-start seed data (`data/seed/`) and seed CPM history
- Tooling: `pyproject.toml` (ruff / black / mypy / pytest / coverage) and GitHub Actions CI

Implementation code for each layer is added in subsequent phases per the
[master build directive](#roadmap).

## Repository layout

```
config/        settings, weights, platforms, thresholds, emotion_weights (+ cpm seed)
data/          raw, normalized, graph (WAL), embeddings (768d), events, time_series,
               feedback/attribution_snapshots, seed
ingestion/     base_collector + per-source collectors (naver, reddit, youtube, rss, ...)
processing/    normalizer, cleaner, deduplicator (MinHash/SimHash), language_detector
compliance/    robots_checker, tos_validator, copyright_scorer, pii_masker        [Layer 2.5]
nlp/           entity_extractor, intent/emotion, topic_cluster, entity_normalizer
graph/         node/edge builders, graph_store (adapter), versioning, propagation, query
time_engine/   trend_detector, decay_model, seasonality
event_engine/  event_db, event_matcher
feature_engine/feature_builder, vectorizer (mpnet 768d)
scoring_engine/revenue_model, probability_model, graph_score, ranking
decision_engine/selector (Thompson), optimizer (Markowitz)
content_factory/generators + quality_gate                                          [Layer 9.5]
publisher/     per-channel publishers + saga_coordinator
feedback_engine/metrics, analyzer, weight_updater, attribution_scheduler
experiments/   ab_test_manager, variant_router, statistical_significance
database/      sqlite / postgres / neo4j / vector_db + backup_manager
api/           app + routes (graph, scoring, review_queue)
jobs/          daily_pipeline, hourly_trend_update, pipeline_orchestrator
tests/         unit / integration / golden_dataset
utils/         logger, timer, retry, auth_manager, cost_tracker, budget_controller
```

## Config files (`config/`)

| File | Purpose | Key refs |
|------|---------|----------|
| `settings.yaml` | graph backend, embeddings (768d), NLP routing, datastores, budget, backup, cold start | DD-006, QA-013, QA-027 |
| `weights.yaml` | GraphScore weights (sum=1.0), edge defaults, CTR Beta priors, funnel priors, risk penalty, decay (ln2/7), adaptive LR, bounds | DD-002, QA-009/014/017/025 |
| `platforms.yaml` | per-platform quota, revenue type, content constraints, backoff, fallback | DD-001, QA-002/016 |
| `thresholds.yaml` | velocity/acceleration states, dedup, decision (Thompson/diversity), quality gate, attribution | DD-008/010, QA-006/011/019 |
| `emotion_weights.yaml` | 6-emotion revenue boost coefficients | DD-005 |
| `cpm_history.seed.json` | seed CPM values (weekly refresh in prod) | QA-015 |

## Getting started

```bash
# 1. Python 3.11
python --version

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure secrets
cp .env.example .env   # then fill in values

# 4. Validate config loads
python -m utils.config_loader
```

## Roadmap

| Phase | Focus |
|-------|-------|
| **0** | Foundation infra: structure, env, configs, tooling, CI *(current)* |
| 1 | Ingestion + normalization (CircuitBreaker, NER, MinHash, GraphStore P1) |
| 2 | Graph + scoring (Velocity/Acceleration, multi-stream revenue, Thompson) |
| 3 | Content + quality gate (generators, fact/dup/readability/toxicity, budget) |
| 4 | Publish + feedback loop (Saga, attribution snapshots, weight updater, observability) |
| 5 | Optimization + scale-up (A/B, Neo4j migration, MAPE ≤ 25%) |
