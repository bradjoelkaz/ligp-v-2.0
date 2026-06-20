"""Tests for production scheduling + resilient run wrapper (orchestration/schedule.py)."""

from __future__ import annotations

from orchestration import schedule


class FakeStore:
    def __init__(self, weights=None, topics=None):
        self._weights = weights or {"w_trend": 0.4}
        self._topics = topics or [{"title": "last good topic"}]

    def init_db(self):
        pass

    def load_weights(self):
        return dict(self._weights)

    def get_latest_trends(self, limit=10):
        return list(self._topics)


def test_run_with_recovery_success():
    out = schedule.run_with_recovery(
        runner=lambda: {"status": "done"}, store=FakeStore(), alerter=lambda t, m: None
    )
    assert out["ok"] is True
    assert out["result"] == {"status": "done"}


def test_run_with_recovery_failure_alerts_and_recovers():
    alerts = []

    def boom():
        raise RuntimeError("network down")

    out = schedule.run_with_recovery(
        runner=boom, store=FakeStore(), alerter=lambda t, m: alerts.append((t, m))
    )
    assert out["ok"] is False
    assert "network down" in out["error"]
    assert out["recovered"]["weights"] == {"w_trend": 0.4}
    assert out["recovered"]["topics"] == [{"title": "last good topic"}]
    assert alerts and "network down" in alerts[0][1]


def test_recover_from_store_handles_errors():
    class BadStore:
        def init_db(self):
            raise RuntimeError("db gone")

        def load_weights(self):  # pragma: no cover - not reached
            return {}

        def get_latest_trends(self, limit=10):  # pragma: no cover
            return []

    recovered = schedule._recover_from_store(BadStore())
    assert recovered == {"weights": {}, "topics": []}


def test_register_prefect_schedule_falls_back_to_cron(monkeypatch):
    # Force the prefect import to fail so we hit the cron-guidance branch.
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("prefect"):
            raise ImportError("no prefect")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    out = schedule.register_prefect_schedule(interval_hours=6)
    assert out["scheduled"] is False
    assert out["engine"] == "cron"
    assert out["cron"] == "0 */6 * * *"
