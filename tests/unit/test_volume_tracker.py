"""Unit tests for the Layer-4 volume tracker (time_engine/volume_tracker.py)."""

from __future__ import annotations

from datetime import datetime

import pytest

from time_engine import volume_tracker as vt


class FakeStore:
    """In-memory stand-in for database.db_store used by the tracker."""

    def __init__(self, series=None):
        self.recorded = []
        self._series = series or {}

    def record_term_volumes(self, counts, ts=None):
        self.recorded.append((counts, ts))

    def get_term_series(self, term, limit=200):
        return self._series.get(term, [])


# --- count_term_volumes ----------------------------------------------------


def test_count_term_volumes_ko_en_case_insensitive():
    articles = [
        {"title": "OpenAI releases model", "text": "AI breakthrough"},
        {"title": "삼성 갤럭시", "text": "AI 카메라"},
        {"title": "Market", "text": "openai again"},
    ]
    counts = vt.count_term_volumes(articles, ["OpenAI", "AI", "삼성", "비트코인", ""])
    assert counts["OpenAI"] == 2
    assert counts["AI"] == 3
    assert counts["삼성"] == 1
    assert counts["비트코인"] == 0
    assert "" not in counts  # blank terms skipped


# --- timestamp parsing -----------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2026-06-20 01:02:03", datetime(2026, 6, 20, 1, 2, 3)),
        ("2026-06-20T01:02:03", datetime(2026, 6, 20, 1, 2, 3)),
        ("2026-06-20", datetime(2026, 6, 20)),
    ],
)
def test_parse_ts(raw, expected):
    assert vt._parse_ts(raw) == expected


def test_parse_ts_invalid_returns_min():
    assert vt._parse_ts("not-a-date") == datetime.min


# --- velocity label --------------------------------------------------------


def test_format_velocity_label():
    assert vt.format_velocity_label(0.35) == "+35%/24h"
    assert vt.format_velocity_label(-0.1, window_hours=6) == "-10%/6h"


# --- record_snapshot -------------------------------------------------------


def test_record_snapshot_injected_store():
    store = FakeStore()
    articles = [{"title": "AI news", "text": "more AI"}]
    counts = vt.record_snapshot(articles, ["AI", "크립토"], store=store)
    assert counts == {"AI": 1, "크립토": 0}
    assert store.recorded and store.recorded[0][0] == counts


# --- analyze_tracked -------------------------------------------------------


def test_analyze_tracked_computes_velocity_and_state():
    series = {
        "OpenAI": [
            ("2026-06-18 00:00:00", 10.0),
            ("2026-06-19 00:00:00", 10.0),
            ("2026-06-20 00:00:00", 30.0),
        ]
    }
    store = FakeStore(series)
    res = vt.analyze_tracked(["OpenAI", "없음"], store=store)
    assert len(res) == 1  # term with no series is skipped
    row = res[0]
    assert row["term"] == "OpenAI"
    assert row["velocity"] == pytest.approx(2.0)
    assert row["velocity_label"] == "+200%/24h"
    assert row["state"] == "viral"
    assert row["state_ko"] == "급상승"
    assert row["volume"] == 30.0
    assert row["points"] == 3


def test_analyze_tracked_sorts_and_limits():
    series = {
        "A": [("2026-06-20 00:00:00", 5.0)],
        "B": [("2026-06-20 00:00:00", 50.0)],
    }
    res = vt.analyze_tracked(["A", "B"], store=FakeStore(series), top=1)
    assert len(res) == 1 and res[0]["term"] == "B"  # highest volume first


def test_state_ko_mapping_complete():
    for eng in ("viral", "rising", "peaking", "falling", "stable"):
        assert eng in vt.STATE_KO


# --- default-store integration (covers lazy db_store import path) ----------


def test_default_store_integration(tmp_path, monkeypatch):
    from database import db_store

    monkeypatch.setattr(db_store, "DB_PATH", str(tmp_path / "v.db"))
    db_store.init_db()

    articles = [{"title": "AI surge", "text": "AI AI"}]
    vt.record_snapshot(articles, ["AI"])  # store=None -> real db_store
    res = vt.analyze_tracked(["AI"])  # store=None -> real db_store
    assert res and res[0]["term"] == "AI"
