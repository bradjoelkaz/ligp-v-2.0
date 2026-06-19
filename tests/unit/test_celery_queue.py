"""Unit tests for the Celery async content queue (Phase 17).

Celery is gated with ``importorskip`` so this suite skips cleanly on offline
dev machines without Celery installed, and runs fully in CI (where
``celery[redis]`` is present). No Redis broker is required: we force
``task_always_eager`` so ``.delay()`` executes the task inline in-process, and
drive everything against offline SQLite with the generator/quality-gate stubbed.
"""

from __future__ import annotations

import json

import pytest

# Skip the whole module unless Celery is importable (offline dev has no celery).
pytest.importorskip("celery")

from api.routes import content as content_mod  # noqa: E402
from database.db_adapter import DBAdapter  # noqa: E402
from database.repositories.content_repo import ContentRepository  # noqa: E402
from orchestration import tasks as tasks_mod  # noqa: E402
from orchestration.celery_app import app as celery_app  # noqa: E402


def _repo(url: str) -> ContentRepository:
    return ContentRepository(DBAdapter(url))


def _stub_generation(monkeypatch, *, fail: bool = False) -> None:
    from content_factory import quality_gate
    from content_factory.generators import blog_generator

    async def _fake_gen(self, node, platform, template=None):
        if fail:
            raise RuntimeError("gen down")
        return {"title": "T", "body": "B", "platform": platform, "tags": node.get("tags", [])}

    monkeypatch.setattr(blog_generator.BlogGenerator, "generate_async", _fake_gen)
    monkeypatch.setattr(quality_gate.QualityGate, "check", lambda self, c, p: (True, []))


@pytest.fixture()
def eager(monkeypatch):
    """Force Celery to run tasks inline (no broker) for the duration of a test."""
    monkeypatch.setattr(celery_app.conf, "task_always_eager", True, raising=False)
    monkeypatch.setattr(celery_app.conf, "task_eager_propagates", True, raising=False)
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "1")
    return celery_app


@pytest.mark.unit
def test_celery_app_loads():
    assert celery_app.main == "iigp"
    assert celery_app.conf.broker_url  # broker configured (default redis://...)
    # Task is registered under its explicit name.
    assert "orchestration.tasks.generate_content_task" in celery_app.tasks


@pytest.mark.unit
def test_generate_content_task_success(tmp_path, monkeypatch, eager):
    url = f"sqlite:///{tmp_path / 'c.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    content_mod._persist_pending("cid", "[pending]", "blog")
    _stub_generation(monkeypatch)

    result = tasks_mod.generate_content_task.delay(
        "cid", {"node_id": "n", "name": "Name", "platform": "blog", "tags": ["t"]}
    )
    assert result.get(timeout=5) == "cid"

    repo = _repo(url)
    try:
        row = repo.get("cid")
        assert row["status"] == "completed"
        payload = json.loads(row["payload"])
        assert payload["title"] == "T"
        assert payload["quality_passed"] is True
    finally:
        repo.db.close()


@pytest.mark.unit
def test_generate_content_task_failure_is_recorded(tmp_path, monkeypatch, eager):
    url = f"sqlite:///{tmp_path / 'c.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    content_mod._persist_pending("cid", "[pending]", "blog")
    _stub_generation(monkeypatch, fail=True)

    # _process_content swallows the error and records status=failed; the task
    # itself completes normally (never crashes the worker).
    tasks_mod.generate_content_task.delay("cid", {"node_id": "n", "platform": "blog"}).get(
        timeout=5
    )

    repo = _repo(url)
    try:
        row = repo.get("cid")
        assert row["status"] == "failed"
        assert "error" in json.loads(row["payload"])
    finally:
        repo.db.close()


@pytest.mark.unit
def test_enqueue_celery_false_without_broker(monkeypatch):
    """No broker + not eager -> helper declines so the route falls back."""
    monkeypatch.delenv("CELERY_BROKER_URL", raising=False)
    monkeypatch.delenv("CELERY_TASK_ALWAYS_EAGER", raising=False)
    assert content_mod._enqueue_celery("cid", {"node_id": "n"}) is False


@pytest.mark.unit
def test_enqueue_celery_publishes_when_eager(tmp_path, monkeypatch, eager):
    """With eager mode on, the helper enqueues (and inline-runs) the task."""
    url = f"sqlite:///{tmp_path / 'c.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    content_mod._persist_pending("cid", "[pending]", "blog")
    _stub_generation(monkeypatch)

    assert content_mod._enqueue_celery("cid", {"node_id": "n", "platform": "blog"}) is True

    repo = _repo(url)
    try:
        assert repo.get("cid")["status"] == "completed"
    finally:
        repo.db.close()
