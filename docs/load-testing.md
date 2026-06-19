# Load Testing & Connection-Pool Tuning (Phase 18)

This guide covers stress-testing the IIGP v2.0 API with [Locust](https://locust.io/)
and tuning the PostgreSQL connection pool that backs the API and Celery workers.

---

## 1. Running the load test

Install the dev/test dependencies (includes `locust`):

```bash
pip install -r requirements-dev.txt
```

### Interactive (web UI)

```bash
locust -f tests/performance/locustfile.py --host http://localhost:8000
```

Open http://localhost:8089, set the number of users and spawn rate, and start.

### Headless (CI / scripted)

```bash
locust -f tests/performance/locustfile.py --host http://localhost:8000 \
       --headless --users 50 --spawn-rate 5 --run-time 2m \
       --csv results/iigp
```

A quick sanity check that the file loads and one user can drive traffic:

```bash
locust -f tests/performance/locustfile.py --host http://localhost:8000 \
       --headless --users 1 --spawn-rate 1 --run-time 2s
```

### Authentication

Admin endpoints may require `X-API-Key` (and the API may require
`Authorization: Bearer ...`). The locustfile reads `ADMIN_API_KEY` and
`API_SECRET_KEY` from the environment (default `test_key`) and sends both on
every request, so it works whether or not auth is enabled:

```bash
ADMIN_API_KEY=your_admin_key API_SECRET_KEY=your_api_key \
  locust -f tests/performance/locustfile.py --host http://localhost:8000 --headless ...
```

### Task mix

| Weight | Request                          | Purpose                          |
|-------:|----------------------------------|----------------------------------|
| 40     | `GET /health`                    | Baseline read / liveness         |
| 20     | `GET /content/status/{id}`       | Async-job polling simulation     |
| 15     | `POST /content/generate`         | Write + enqueue (Celery/bg)      |
| 15     | `GET /admin/api/graph`           | Heavier DB-backed read (D3 graph)|
| 10     | `GET /admin/api/content-stats`   | Dashboard aggregate read         |

---

## 2. Connection-pool tuning

The `DBAdapter` (`database/db_adapter.py`) serves PostgreSQL connections from a
psycopg3 `psycopg_pool.ConnectionPool` (the psycopg3 equivalent of psycopg2's
`ThreadedConnectionPool`). SQLite keeps a single persistent connection — no pool
overhead. Connections are always returned in a `finally` block; a transaction
holds one connection for its whole duration.

Tune the pool with environment variables:

| Variable            | Default | Meaning                          |
|---------------------|--------:|----------------------------------|
| `DB_POOL_MIN_CONN`  | 5       | Connections kept warm (min_size) |
| `DB_POOL_MAX_CONN`  | 20      | Hard ceiling (max_size)          |

### Sizing guidance

- **Start from your DB ceiling.** PostgreSQL `max_connections` (default ~100) is
  shared across **every** pool. With API (Gunicorn workers) + Celery workers each
  holding a pool, total peak ≈ `Σ(processes × DB_POOL_MAX_CONN)`. Keep that
  comfortably under `max_connections` (leave headroom for admin/migrations).
- **`max_size`**: raise until added throughput flattens or DB CPU/locks become
  the bottleneck. A common rule of thumb is `((core_count × 2) + effective_spindle_count)`
  per service as a starting point; verify empirically.
- **`min_size`**: set to your steady-state concurrency so warm connections absorb
  bursts without per-request connect latency. Too high wastes idle DB slots.
- If you see "too many clients already" from Postgres, lower `DB_POOL_MAX_CONN`
  or the worker/replica count; if you see request queueing with idle DB, raise it.

---

## 3. Monitoring during the run

Run the load test alongside the Prometheus/Grafana stack (see
`docker-compose.prod.yml`) and watch:

- **`iigp_http_requests_in_progress`** — in-flight concurrency. A steadily
  climbing value while throughput is flat indicates a downstream bottleneck
  (often pool/DB saturation).
- **Request latency histogram** (`iigp_http_request_duration_seconds`) — track
  p50/p95/p99. The "knee" where p95 turns sharply upward as users increase marks
  your practical capacity for the current pool settings.
- **Locust stats** — RPS, failure %, and median/95th response times per endpoint.

### Suggested procedure

1. Baseline: a few users, confirm 0% failures and low latency.
2. Ramp users in steps (e.g. 10 → 50 → 100 → 200), holding each step long enough
   to stabilize.
3. Record the user count where p95 latency crosses your SLO or failures appear —
   that is the capacity limit for the current `DB_POOL_MAX_CONN` / worker count.
4. Adjust `DB_POOL_MAX_CONN` (and/or worker/replica counts), re-run, and compare.
   Stop when more pool size no longer improves throughput (DB-bound).
