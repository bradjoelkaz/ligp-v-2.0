# IIGP v2.0 — Production Deployment Guide

This guide covers deploying the IIGP stack (API, worker, PostgreSQL, Redis,
Prometheus, Pushgateway, Grafana) with `docker-compose.prod.yml`.

## 1. Prerequisites

- Docker + Docker Compose v2
- A host with outbound network (for pulling images) and ports `8000` (API),
  `9090` (Prometheus), `3000` (Grafana) available (configurable).

## 2. Configure environment

```bash
cp .env.production.example .env.production
# Edit .env.production and set all CHANGE_ME secrets.
```

Generate strong keys:

```bash
python -c "import secrets; print(secrets.token_hex(32))"   # API_SECRET_KEY
python -c "import secrets; print(secrets.token_hex(32))"   # ADMIN_API_KEY
```

Key variables (see `.env.production.example` for the full list):

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL DSN. Append `?connect_timeout=2` so the `/health` DB probe fails fast. |
| `POSTGRES_PASSWORD` | Required; compose refuses to start without it. |
| `API_SECRET_KEY` | `X-API-Key` for `/api/*` routes (empty disables auth). |
| `ADMIN_API_KEY` | `X-API-Key` for `POST /admin/api/node|edge`. |
| `PUSHGATEWAY_URL` | Where the worker pushes pipeline metrics (`pushgateway:9091`). |
| `UVICORN_WORKERS` | API worker count (see metrics note below). |
| `GRAFANA_PASSWORD` | Required Grafana admin password. |

## 3. Build & start

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production build
docker compose -f docker-compose.prod.yml --env-file .env.production up -d
docker compose -f docker-compose.prod.yml ps
```

Endpoints once healthy:

- API: `http://<host>:8000` — admin `…/admin/`, metrics `…/metrics`, docs `…/docs`
- Prometheus: `http://<host>:9090`
- Grafana: `http://<host>:3000` (login with `GRAFANA_USER`/`GRAFANA_PASSWORD`)

## 4. Database migrations (Alembic)

The raw-SQL repositories self-create their tables via `CREATE TABLE IF NOT
EXISTS`, but in production run Alembic so the schema is version-managed:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production \
  exec api alembic upgrade head
```

This applies migrations `001` → `002` (graph tables) → `003` (unified
`nodes`/`content`, drops the dead `edges` table). Check current revision:

```bash
docker compose -f docker-compose.prod.yml exec api alembic current
```

> Note: `003` drops & recreates `nodes`/`content`. It assumes those tables hold
> no production data (matching the v2.0 cleanup). Back up first if unsure:
> `pg_dump`.

## 5. Health & readiness

- `GET /health` — `200` when healthy (DB `connected` or `not_configured`),
  `503` when a configured DB is unreachable. Body:

  ```json
  {
    "status": "healthy",
    "timestamp": "2026-06-19T04:00:00+00:00",
    "components": {"database": "connected", "metrics": "enabled"}
  }
  ```

- `GET /ready` — config readiness; `GET /version` — app name/version.

The compose `healthcheck` uses `/health`; dependents wait via `depends_on`.

## 6. Security

- Set `API_SECRET_KEY` to require `X-API-Key` on `/api/*`. Public routes
  (`/health`, `/ready`, `/version`, `/metrics`, `/admin`, `/docs`) bypass it.
- Set `ADMIN_API_KEY` to require `X-API-Key` on the admin graph-mutation
  endpoints (`POST /admin/api/node|edge`). Read-only admin GETs stay public —
  place the `/admin` surface behind a network ACL / reverse-proxy auth for
  production.
- CORS origins are read from `settings.yaml → api.cors_origins` (default `*`);
  restrict this for production.
- Never commit `.env.production`; only the `.example` template is tracked.

## 7. Monitoring

- **API metrics**: scraped by Prometheus from `api:8000/metrics`
  (`iigp_http_*`, `iigp_graph_*`, `iigp_content_generated_total`, …).
- **Worker / pipeline metrics**: the worker process pushes to the Pushgateway
  (`PUSHGATEWAY_URL`), which Prometheus scrapes with `honor_labels: true`
  (see `monitoring/prometheus/prometheus.yml`).
- **Grafana**: datasource + dashboards (`IIGP v2.0 Overview`, `IIGP API`) are
  auto-provisioned from `monitoring/grafana/provisioning`.

### Metrics with multiple API workers

`prometheus_client` keeps metrics per process. With `UVICORN_WORKERS > 1`, each
worker has its own registry, so a single `/metrics` scrape only reflects the
worker that served it. Options:

1. Run the API with `UVICORN_WORKERS=1` (default-friendly, accurate `/metrics`).
2. Enable `prometheus_client` multiprocess mode by setting
   `PROMETHEUS_MULTIPROC_DIR` and wiring a `MultiProcessCollector` (follow-up).

Pipeline/business metrics are unaffected (they flow through the Pushgateway).

## 8. Operations

```bash
# Logs
docker compose -f docker-compose.prod.yml logs -f api worker

# Restart a service
docker compose -f docker-compose.prod.yml restart api

# Stop everything (keeps volumes/data)
docker compose -f docker-compose.prod.yml down

# Stop and DELETE data volumes (destructive)
docker compose -f docker-compose.prod.yml down -v
```
