"""Unit tests for Celery task resilience (Phase 19).

Covers the exponential-backoff auto-retry config and the ``on_failure`` DLQ-style
hook. ``celery`` is gated with ``importorskip`` (offline dev skips; CI runs it),
and the suite forces ``task_always_eager`` so tasks run inline with no broker,
driving everything against offline SQLite with the generator stubbed.
"""

from __future__ import annotations

import json
from unittest import mock

import pytest

pytest.importorskip("celery")

from celery.exceptions import Retry  # noqa: E402

from api.routes import content as content_mod  # noqa: E402
from database.db_adapter import DBAdapter  # noqa: E402
from database.repositories.content_repo import ContentRepository  # noqa: E402
from orchestration import tasks as tasks_mod  # noqa: E402
from orchestration.celery_app import app as celery_app  # noqa: E402


def _repo(url: str) -> ContentRepository:
    return ContentRepository(DBAdapter(url))


def _stub_generation(monkeypatch, *, exc: BaseException | None = None) -> None:
    from content_factory import quality_gate
    from content_factory.generators import blog_generator

    async def _fake_gen(self, node, platform, template=None):
        if exc is not None:
            raise exc
        return {"title": "T", "body": "B", "platform": platform, "tags": node.get("tags", [])}

    monkeypatch.setattr(blog_generator.BlogGenerator, "generate_async", _fake_gen)
    monkeypatch.setattr(quality_gate.QualityGate, "check", lambda self, c, p: (True, []))


@pytest.fixture()
def eager(monkeypatch):
    monkeypatch.setattr(celery_app.conf, "task_always_eager", True, raising=False)
    monkeypatch.setattr(celery_app.conf, "task_eager_propagates", True, raising=False)
    monkeypatch.setenv("CELERY_TASK_ALWAYS_EAGER", "1")
    return celery_app


@pytest.mark.unit
def test_task_retry_configuration():
    """The task advertises the documented backoff/retry policy."""
    t = tasks_mod.generate_content_task
    assert t.max_retries == 5
    assert t.retry_backoff is True
    assert t.retry_backoff_max == 300
    assert t.retry_jitter is True
    # Custom base provides the failure hook.
    assert isinstance(t, tasks_mod.DatabaseAlertTask)
    # Builtin transient network errors are retryable.
    assert ConnectionError in tasks_mod.RETRYABLE_ERRORS
    assert ValueError not in tasks_mod.RETRYABLE_ERRORS


@pytest.mark.unit
def test_non_retryable_error_marks_failed_via_on_failure(tmp_path, monkeypatch, eager):
    """A non-retryable error fails fast and on_failure records status=failed."""
    url = f"sqlite:///{tmp_path / 'c.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    content_mod._persist_pending("cid", "[pending]", "blog")
    _stub_generation(monkeypatch, exc=ValueError("bad input"))

    with pytest.raises(ValueError):
        tasks_mod.generate_content_task.delay("cid", {"node_id": "n", "platform": "blog"}).get(
            timeout=5
        )

    repo = _repo(url)
    try:
        row = repo.get("cid")
        assert row["status"] == "failed"
        assert json.loads(row["payload"])["error"] == "bad input"
    finally:
        repo.db.close()


@pytest.mark.unit
def test_on_failure_hook_records_failed_directly(tmp_path, monkeypatch):
    """on_failure writes status=failed for the content_id in args[0]."""
    url = f"sqlite:///{tmp_path / 'c.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    content_mod._persist_pending("cid", "[pending]", "blog")

    tasks_mod.generate_content_task.on_failure(
        RuntimeError("boom"), "task-123", ("cid", {}), {}, None
    )

    repo = _repo(url)
    try:
        row = repo.get("cid")
        assert row["status"] == "failed"
        assert json.loads(row["payload"])["error"] == "boom"
    finally:
        repo.db.close()


@pytest.mark.unit
def test_on_failure_no_args_is_safe():
    """on_failure must not raise when args is empty (no content_id)."""
    tasks_mod.generate_content_task.on_failure(RuntimeError("x"), "task-1", (), {}, None)


@pytest.mark.unit
def test_retryable_error_triggers_retry(tmp_path, monkeypatch, eager):
    """A retryable (transient) error routes through self.retry (autoretry_for)."""
    url = f"sqlite:///{tmp_path / 'c.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    content_mod._persist_pending("cid", "[pending]", "blog")
    _stub_generation(monkeypatch, exc=ConnectionError("db blip"))

    # Intercept the retry so we assert it is scheduled without looping/sleeping.
    retry_mock = mock.Mock(side_effect=Retry("scheduled"))
    monkeypatch.setattr(tasks_mod.generate_content_task, "retry", retry_mock)

    with pytest.raises(Retry):
        tasks_mod.generate_content_task.apply(
            args=("cid", {"node_id": "n", "platform": "blog"})
        ).get()

    assert retry_mock.called
    # The retried exception is the transient error we raised.
    _, kwargs = retry_mock.call_args
    assert isinstance(kwargs.get("exc"), ConnectionError)
