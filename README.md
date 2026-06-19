# IIGP v2.0 — Intelligent Information Graph Pipeline

> Graph-centric, probability-driven content revenue engine:
> data ingestion → knowledge graph → scoring → content generation → publishing → feedback loop.

## Architecture

```
Data Sources (Naver, Reddit, YouTube, RSS)
    | Ingestion Layer (Phase 1)
Document Normalization + Deduplication
    | NLP Processing (Phase 3)
Knowledge Graph (Phase 2)
    | Scoring Engine (Phase 2)
Content Factory (Phase 4)
    | Publishing + Feedback (Phase 4)
Experiments / A-B Testing (Phase 5)
    | Orchestration (Phase 5)
Production Hardening (Phase 7)
    | Observability (Phase 8)
Admin Dashboard + Monitoring + API Auth (Phase 9)
```

## Quick Start

### Prerequisites
- Python 3.11+
- Docker and Docker Compose
- API keys (Naver, Reddit, YouTube, OpenAI — all optional; the system degrades gracefully)

### Development
```bash
# 1. Clone and set up
git clone https://github.com/bradjoelkaz/ligp-v-2.0.git
cd ligp-v-2.0
cp .env.example .env
pip install -r requirements-dev.txt

# 2. Run tests
pytest tests/unit/ -q
pytest tests/integration/ -q

# 3. Start the API server (factory pattern)
uvicorn api.main:create_app --factory --reload --port 8000
```

### Docker (full stack)
```bash
cp .env.example .env
docker-compose up -d
# API        -> http://localhost:8000      (admin: /admin/, metrics: /metrics)
# Prefect    -> http://localhost:4200
# Prometheus -> http://localhost:9090
# Grafana    -> http://localhost:3000      (admin / admin)
```

## Project Structure

```
├── api/                      # FastAPI application
│   ├── main.py               # App factory (create_app) + lifespan
│   ├── metrics.py            # Prometheus ASGI middleware + /metrics
│   ├── admin/                # Admin dashboard (Jinja2 + D3.js)
│   ├── middleware/           # API key authentication middleware
│   └── routes/               # health, content, graph, experiments routers
├── ingestion/                # Data collection layer
│   ├── base_collector.py     # Abstract collector + RawDocument
│   ├── bootstrap_pipeline.py # Cold-start seed graph bootstrap
│   ├── schema.py             # Ingestion schemas
│   └── collectors/           # Naver, Reddit, YouTube
├── processing/               # Deduplication + language detection
├── graph/                    # Knowledge graph engine (nodes/edges/queries)
├── scoring_engine/           # GraphScore, revenue model, probability, ranking
├── nlp/                      # NER, intent/emotion, topic clustering
├── content_factory/          # Content generation + quality gate
├── decision_engine/          # Selection (Thompson) + optimization
├── feedback_engine/          # Performance feedback loop + weight updates
├── time_engine/              # Temporal decay, seasonality, trend detection
├── experiments/              # A-B testing framework
├── orchestration/            # Pipeline orchestration (Prefect)
│   ├── flows/                # daily_pipeline, realtime_ingestion
│   └── worker.py             # Background worker entrypoint
├── database/                 # Adapters, repositories, Alembic migrations
├── monitoring/               # Prometheus config + Grafana dashboards
├── utils/                    # config_loader, logger, rate_limiter, cache, ...
├── config/                   # YAML configuration files
├── tests/
│   ├── unit/                 # Unit tests (213+)
│   └── integration/          # E2E integration tests
├── Dockerfile                # Multi-stage production build
├── docker-compose.yml        # Full stack (api, worker, db, redis, prefect, prometheus, grafana)
└── .github/workflows/ci.yml  # 4-job CI pipeline
```

## Environment Variables

See `.env.example` for the complete list. Key variables:

| Variable | Required | Description |
|---|---|---|
| `API_SECRET_KEY` | No | API key for `/api/*` routes (empty = auth disabled) |
| `NAVER_CLIENT_ID` / `NAVER_CLIENT_SECRET` | No | Naver Search API credentials |
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | No | Reddit OAuth credentials |
| `YOUTUBE_API_KEY` | No | YouTube Data API v3 key |
| `OPENAI_API_KEY` | No | GPT model for content generation (template fallback otherwise) |
| `SLACK_WEBHOOK_URL` | No | Slack notification webhook |
| `DATABASE_URL` | No | PostgreSQL URL (default: SQLite) |
| `REDIS_URL` | No | Redis URL (default: in-memory fallback) |
| `GRAFANA_PASSWORD` | No | Grafana admin password (default: admin) |

## Testing

```bash
# Unit tests with coverage (core packages gated at 90%)
pytest tests/unit/ -q --cov --cov-fail-under=90

# Integration tests
pytest tests/integration/ -q -v

# Lint and format
black --check .
ruff check .
```

Heavy third-party libraries are lazily imported, so the test suite runs in
dependency-light environments; tests that require an optional dependency are
guarded with `pytest.importorskip` and skip cleanly when it is absent.

## Observability

- **Prometheus metrics**: exposed at `/metrics` on the API server
  (`iigp_http_requests_total`, `iigp_http_request_duration_seconds`,
  `iigp_http_requests_in_progress`).
- **Grafana**: pre-provisioned Prometheus datasource and dashboards
  (`IIGP v2.0 Overview`, `IIGP API — Observability`) at `http://localhost:3000`.
- **Admin dashboard**: `http://localhost:8000/admin/`.

## Authentication

Set `API_SECRET_KEY` to require an `X-API-Key` header on `/api/*` routes.
Public routes (`/health`, `/ready`, `/version`, `/metrics`, `/admin`, `/docs`)
always bypass authentication. Leave the variable empty to disable auth in
development.

## CI Pipeline

The GitHub Actions workflow runs four sequential jobs:

1. **Lint + Format + Config** — `ruff`, `black --check`, YAML config validation
2. **Unit Tests + Coverage** — full unit suite, core packages gated at 90%
3. **Docker Build** — multi-stage image build + `/health` and `/metrics` smoke test
4. **Integration Tests** — end-to-end API and pipeline tests

## License

Private — All rights reserved.
