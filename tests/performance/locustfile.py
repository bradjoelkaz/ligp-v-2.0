"""Locust load-test scenarios for the IIGP v2.0 API (Phase 18).

Run (the API must be reachable at --host)::

    locust -f tests/performance/locustfile.py --host http://localhost:8000

Headless smoke / CI sanity::

    locust -f tests/performance/locustfile.py --host http://localhost:8000 \\
           --headless --users 1 --spawn-rate 1 --run-time 2s

This file is the Locust entrypoint, not a pytest module: it is named
``locustfile.py`` (not ``test_*.py``) so pytest never collects it, and ``locust``
is imported at module top so it only loads under the ``locust`` CLI. Admin
requests carry ``X-API-Key`` from ``ADMIN_API_KEY`` (default ``test_key``) so the
suite works whether or not admin auth is enabled.
"""

import os
import random

from locust import HttpUser, between, task

ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "test_key")
API_SECRET_KEY = os.environ.get("API_SECRET_KEY", "test_key")

# Sent on every request; harmless when auth is disabled, required when it isn't.
_AUTH_HEADERS = {"X-API-Key": ADMIN_API_KEY, "Authorization": f"Bearer {API_SECRET_KEY}"}

_PLATFORMS = ("blog", "youtube", "newsletter")


class IIGPUser(HttpUser):
    """Simulates a mixed read/write client: health, generate, poll, admin reads."""

    wait_time = between(0.5, 2.0)

    def on_start(self) -> None:
        # Seed a content id so the status-poll task has something to query even
        # before this user has generated anything.
        self._content_ids: list[str] = []

    @task(40)
    def health(self) -> None:
        self.client.get("/health", name="GET /health")

    @task(15)
    def generate_content(self) -> None:
        payload = {
            "node_id": f"node-{random.randint(1, 500)}",
            "name": f"load-test-{random.randint(1, 10_000)}",
            "platform": random.choice(_PLATFORMS),
            "tags": ["load", "test"],
        }
        with self.client.post(
            "/content/generate",
            json=payload,
            headers=_AUTH_HEADERS,
            name="POST /content/generate",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                cid = (resp.json() or {}).get("content_id")
                if cid:
                    self._content_ids.append(cid)
                    # Bound memory under long runs.
                    self._content_ids = self._content_ids[-50:]
                resp.success()
            else:
                resp.failure(f"unexpected status {resp.status_code}")

    @task(20)
    def poll_status(self) -> None:
        if not self._content_ids:
            return
        cid = random.choice(self._content_ids)
        # 404 is acceptable (id may not be persisted without a DB) -> not a failure.
        with self.client.get(
            f"/content/status/{cid}",
            headers=_AUTH_HEADERS,
            name="GET /content/status/{id}",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 404):
                resp.success()
            else:
                resp.failure(f"unexpected status {resp.status_code}")

    @task(15)
    def admin_graph(self) -> None:
        self.client.get("/admin/api/graph", headers=_AUTH_HEADERS, name="GET /admin/api/graph")

    @task(10)
    def admin_content_stats(self) -> None:
        self.client.get(
            "/admin/api/content-stats",
            headers=_AUTH_HEADERS,
            name="GET /admin/api/content-stats",
        )
