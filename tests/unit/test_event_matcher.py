"""Tests for EventDB and EventMatcher (DD-007)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from event_engine.event_db import EventDB
from event_engine.event_matcher import EventMatcher


@pytest.fixture()
def db():
    d = EventDB(":memory:")
    yield d
    d.close()


@pytest.mark.unit
def test_event_insert_and_active(db):
    now = datetime(2026, 6, 1, 12, 0, 0)
    eid = db.insert(
        {
            "name": "Summer Sale",
            "start_date": now - timedelta(days=1),
            "end_date": now + timedelta(days=1),
            "type": "planned",
            "tags": ["sale", "summer"],
            "boost_multiplier": 1.5,
        }
    )
    assert eid
    active = db.get_active_events(now)
    assert len(active) == 1
    assert active[0]["tags"] == ["sale", "summer"]


@pytest.mark.unit
def test_event_inactive_outside_window(db):
    now = datetime(2026, 6, 1)
    db.insert(
        {
            "name": "Old",
            "start_date": now - timedelta(days=10),
            "end_date": now - timedelta(days=5),
            "type": "trending",
            "tags": ["x"],
        }
    )
    assert db.get_active_events(now) == []


@pytest.mark.unit
def test_event_invalid_type(db):
    with pytest.raises(ValueError):
        db.insert(
            {
                "name": "X",
                "start_date": "2026-01-01",
                "end_date": "2026-01-02",
                "type": "bogus",
                "tags": [],
            }
        )


@pytest.mark.unit
def test_event_upsert_updates(db):
    eid = db.insert(
        {
            "event_id": "e1",
            "name": "A",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "type": "trending",
            "tags": ["t"],
        }
    )
    db.upsert(
        {
            "event_id": eid,
            "name": "B",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "type": "trending",
            "tags": ["t"],
        }
    )
    got = db.get_by_tag("t")
    assert len(got) == 1 and got[0]["name"] == "B"


@pytest.mark.unit
def test_matcher_jaccard_match():
    m = EventMatcher()
    node = {"tags": ["ai", "tech", "gpu"]}
    events = [{"name": "AI Expo", "tags": ["ai", "tech", "robotics"], "boost_multiplier": 2.0}]
    matched = m.match(node, events)
    # jaccard = |{ai,tech}| / |{ai,tech,gpu,robotics}| = 2/4 = 0.5 >= 0.30
    assert len(matched) == 1


@pytest.mark.unit
def test_matcher_no_match_low_overlap():
    m = EventMatcher()
    node = {"tags": ["ai", "tech", "gpu", "ml", "data"]}
    events = [{"name": "Cooking", "tags": ["food"], "boost_multiplier": 2.0}]
    assert m.match(node, events) == []


@pytest.mark.unit
def test_matcher_qid_match():
    m = EventMatcher()
    node = {"tags": [], "qid": "Q42"}
    events = [{"name": "E", "tags": [], "qids": ["Q42"], "boost_multiplier": 1.5}]
    assert len(m.match(node, events)) == 1


@pytest.mark.unit
def test_event_boost_range():
    m = EventMatcher()
    assert m.compute_event_boost([]) == 1.0
    boost = m.compute_event_boost([{"boost_multiplier": 2.0}, {"boost_multiplier": 1.5}])
    assert 1.0 <= boost <= 3.0


@pytest.mark.unit
def test_event_boost_capped():
    m = EventMatcher()
    huge = [{"boost_multiplier": 5.0} for _ in range(5)]
    assert m.compute_event_boost(huge) == 3.0
