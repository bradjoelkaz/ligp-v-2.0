"""daily_pipeline() must route through run_with_recovery (Phase 10)."""

from __future__ import annotations

import orchestration.schedule as schedule
from orchestration.flows import daily_pipeline as dp


def test_daily_pipeline_delegates_to_run_with_recovery(monkeypatch):
    captured = {}

    def fake_recovery(runner=None, **kwargs):
        captured["runner"] = runner
        return {"ok": True, "result": "delegated"}

    monkeypatch.setattr(schedule, "run_with_recovery", fake_recovery)
    out = dp.daily_pipeline()
    assert out == {"ok": True, "result": "delegated"}
    # The live runner is passed explicitly (no recursion into daily_pipeline).
    assert captured["runner"] is dp._live_run


def test_run_with_recovery_uses_live_run_on_failure(monkeypatch):
    """A failing live run is caught: alert sent + state recovered from store."""
    alerts = []

    class FakeStore:
        def init_db(self):
            pass

        def load_weights(self):
            return {"w_trend": 0.5}

        def get_latest_trends(self, limit=10):
            return [{"title": "prev"}]

    def boom():
        raise RuntimeError("collector down")

    out = schedule.run_with_recovery(
        runner=boom, store=FakeStore(), alerter=lambda t, m: alerts.append(m)
    )
    assert out["ok"] is False
    assert out["recovered"]["weights"] == {"w_trend": 0.5}
    assert alerts
