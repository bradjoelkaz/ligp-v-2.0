"""SQLite persistence for raw articles, analyzed topics, and generated prompts.

This is a lightweight, self-contained store for the real-time trends dashboard
(admin ``/trends``). It is intentionally separate from :mod:`database.db_adapter`
(which backs the DATABASE_URL-configured knowledge graph): the trends asset
store always lives in a fixed local SQLite file (``data/iigp_trends.db``) so
collected/analyzed trends survive restarts and can be restored when the network
or LLM is unavailable.

Tables
------
- ``raw_articles``: deduplicated raw documents from the collectors (PK source_id).
- ``trend_topics``: analyzed topic cards including Suno music prompts and
  Nano Banana album-cover image prompts (entities stored as a JSON string).

Every function is defensive: failures are logged and never raised to the caller
so the dashboard request path stays resilient.
"""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Any

from utils.logger import get_logger

_log = get_logger(__name__)

# <repo_root>/data/iigp_trends.db  (this file lives at <repo_root>/database/db_store.py)
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "iigp_trends.db")


def init_db() -> None:
    """Create the SQLite tables for raw documents and analyzed topics if absent."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()

            # 1. Raw collected documents (dedup on source_id).
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS raw_articles (
                    source_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    text TEXT,
                    source_url TEXT,
                    platform TEXT,
                    published_at TEXT,
                    collected_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """)

            # 2. Analyzed trend topics (entities + prompts).
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trend_topics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    category TEXT,
                    summary TEXT,
                    entities TEXT,            -- JSON-encoded list
                    trend_score REAL,
                    velocity TEXT,
                    acceleration TEXT,
                    expected_revenue TEXT,
                    copyright_risk REAL,
                    suno_prompt TEXT,         -- generated Suno music prompt
                    image_prompt TEXT,        -- generated Nano Banana album-cover prompt
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """)

            # 3. Per-term mention volume time-series (Layer 4 input).
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS term_volume (
                    term TEXT NOT NULL,
                    volume INTEGER NOT NULL,
                    ts DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """)
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_term_volume_term_ts ON term_volume (term, ts)"
            )
            conn.commit()
            _log.info("sqlite_db_initialized", extra={"path": DB_PATH})
    except Exception as exc:  # noqa: BLE001 - persistence must never crash callers
        _log.error("sqlite_db_init_failed", extra={"error": str(exc)})


def save_raw_articles(articles: list[dict[str, Any]]) -> None:
    """Insert or replace collected raw articles (dedup on ``source_id``)."""
    if not articles:
        return
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.executemany(
                """
                INSERT OR REPLACE INTO raw_articles
                    (source_id, title, text, source_url, platform, published_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        art.get("source_id"),
                        art.get("title", ""),
                        art.get("text", ""),
                        art.get("source_url", ""),
                        art.get("platform", ""),
                        art.get("published_at", ""),
                    )
                    for art in articles
                ],
            )
            conn.commit()
            _log.info("saved_raw_articles_to_sqlite", extra={"count": len(articles)})
    except Exception as exc:  # noqa: BLE001
        _log.error("save_raw_articles_failed", extra={"error": str(exc)})


def save_trend_topics(topics: list[dict[str, Any]]) -> None:
    """Append analyzed topics (entities JSON-encoded) to ``trend_topics``."""
    if not topics:
        return
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            for tp in topics:
                entities_str = json.dumps(tp.get("entities", []), ensure_ascii=False)
                cursor.execute(
                    """
                    INSERT INTO trend_topics (
                        title, category, summary, entities, trend_score,
                        velocity, acceleration, expected_revenue, copyright_risk,
                        suno_prompt, image_prompt
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tp.get("title", ""),
                        tp.get("category", "기타"),
                        tp.get("summary", ""),
                        entities_str,
                        tp.get("trend_score", 0.0),
                        tp.get("velocity", ""),
                        tp.get("acceleration", ""),
                        tp.get("expected_revenue", "$0.00"),
                        tp.get("copyright_risk", 0.0),
                        tp.get("suno_prompt", ""),
                        tp.get("image_prompt", ""),
                    ),
                )
            conn.commit()
            _log.info("saved_trend_topics_to_sqlite", extra={"count": len(topics)})
    except Exception as exc:  # noqa: BLE001
        _log.error("save_trend_topics_failed", extra={"error": str(exc)})


def get_latest_trends(limit: int = 10) -> list[dict[str, Any]]:
    """Return the most recently stored topics (newest first, then by score)."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM trend_topics
                ORDER BY created_at DESC, trend_score DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()

            topics: list[dict[str, Any]] = []
            for row in rows:
                topics.append(
                    {
                        "title": row["title"],
                        "category": row["category"],
                        "summary": row["summary"],
                        "entities": json.loads(row["entities"]) if row["entities"] else [],
                        "trend_score": row["trend_score"],
                        "velocity": row["velocity"],
                        "acceleration": row["acceleration"],
                        "expected_revenue": row["expected_revenue"],
                        "copyright_risk": row["copyright_risk"],
                        "suno_prompt": row["suno_prompt"] or "",
                        "image_prompt": row["image_prompt"] or "",
                        "created_at": row["created_at"],
                    }
                )
            return topics
    except Exception as exc:  # noqa: BLE001
        _log.error("get_latest_trends_failed", extra={"error": str(exc)})
        return []


def get_recent_articles(limit: int = 500) -> list[dict[str, Any]]:
    """Return the most recently collected raw articles (newest first)."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT source_id, title, text, source_url, platform, published_at
                FROM raw_articles
                ORDER BY collected_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]
    except Exception as exc:  # noqa: BLE001
        _log.error("get_recent_articles_failed", extra={"error": str(exc)})
        return []


def record_term_volumes(counts: dict[str, int], ts: str | None = None) -> None:
    """Append a volume snapshot for each term to the ``term_volume`` series.

    ``ts`` is an optional ISO/SQLite timestamp; when omitted SQLite uses
    ``CURRENT_TIMESTAMP``. Terms with a volume of 0 are still recorded so the
    series captures decay back to zero.
    """
    if not counts:
        return
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            if ts is None:
                cursor.executemany(
                    "INSERT INTO term_volume (term, volume) VALUES (?, ?)",
                    [(term, int(vol)) for term, vol in counts.items()],
                )
            else:
                cursor.executemany(
                    "INSERT INTO term_volume (term, volume, ts) VALUES (?, ?, ?)",
                    [(term, int(vol), ts) for term, vol in counts.items()],
                )
            conn.commit()
            _log.info("recorded_term_volumes", extra={"terms": len(counts)})
    except Exception as exc:  # noqa: BLE001
        _log.error("record_term_volumes_failed", extra={"error": str(exc)})


def get_term_series(term: str, limit: int = 200) -> list[tuple[str, float]]:
    """Return ``(ts, volume)`` points for ``term`` in ascending time order."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT ts, volume FROM term_volume
                WHERE term = ?
                ORDER BY ts ASC
                LIMIT ?
                """,
                (term, limit),
            )
            return [(str(ts), float(vol)) for ts, vol in cursor.fetchall()]
    except Exception as exc:  # noqa: BLE001
        _log.error("get_term_series_failed", extra={"term": term, "error": str(exc)})
        return []
