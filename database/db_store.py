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
    try:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
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
                    language TEXT,
                    country TEXT,
                    views INTEGER DEFAULT 0,
                    likes INTEGER DEFAULT 0,
                    comments INTEGER DEFAULT 0,
                    shares INTEGER DEFAULT 0,
                    collected_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """)
            # Forward-compat: add L2 columns to pre-existing DBs (best-effort).
            for _col, _decl in (
                ("language", "TEXT"),
                ("country", "TEXT"),
                ("views", "INTEGER DEFAULT 0"),
                ("likes", "INTEGER DEFAULT 0"),
                ("comments", "INTEGER DEFAULT 0"),
                ("shares", "INTEGER DEFAULT 0"),
            ):
                try:
                    cursor.execute(f"ALTER TABLE raw_articles ADD COLUMN {_col} {_decl}")
                except sqlite3.OperationalError:
                    pass  # column already exists

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

            # 4. Performance feedback for the L7 self-calibration loop.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS content_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content_id TEXT,
                    platform TEXT,
                    expected_score REAL,
                    actual_score REAL,
                    features TEXT,            -- JSON: {component: feature_value}
                    views INTEGER,
                    clicks INTEGER,
                    subscribers INTEGER,
                    revenue REAL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """)

            # 5. Calibrated opportunity-score weights (loaded on next run).
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS weights_state (
                    component TEXT PRIMARY KEY,
                    weight REAL NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """)

            # 6. Cost ledger (API/resource spend) for the OS dashboard ROI.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS cost_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT,
                    usd REAL NOT NULL,
                    ts DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """)

            # 7. Generated content assets (e.g. YouTube 2-column scripts).
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS generated_content (
                    content_id TEXT PRIMARY KEY,
                    format TEXT,
                    platform TEXT,
                    title TEXT,
                    body TEXT,
                    payload TEXT,            -- full JSON content object
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """)

            # 8. Deployment ledger (virtual multi-channel publishing).
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS deployments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content_id TEXT,
                    platform TEXT,
                    url TEXT,
                    status TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """)

            # 9. Calibrated-weights history (OS dashboard trend chart).
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS weights_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    weights TEXT NOT NULL,    -- JSON snapshot
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """)
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
                    (source_id, title, text, source_url, platform, published_at,
                     language, country, views, likes, comments, shares)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        art.get("source_id"),
                        art.get("title", ""),
                        art.get("text", ""),
                        art.get("source_url", ""),
                        art.get("platform", ""),
                        art.get("published_at", ""),
                        art.get("language", ""),
                        art.get("country", ""),
                        int((art.get("engagement") or {}).get("views", 0) or 0),
                        int((art.get("engagement") or {}).get("likes", 0) or 0),
                        int((art.get("engagement") or {}).get("comments", 0) or 0),
                        int((art.get("engagement") or {}).get("shares", 0) or 0),
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
                SELECT source_id, title, text, source_url, platform, published_at,
                       language, country, views, likes, comments, shares
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


# --- L7 feedback + calibrated weights + cost ledger -------------------------


def record_content_feedback(
    content_id: str,
    platform: str,
    expected_score: float,
    actual_score: float,
    features: dict[str, float] | None = None,
    metrics: dict[str, Any] | None = None,
) -> None:
    """Persist one performance-feedback record for the L7 calibration loop."""
    metrics = metrics or {}
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO content_feedback (
                    content_id, platform, expected_score, actual_score,
                    features, views, clicks, subscribers, revenue
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    content_id,
                    platform,
                    float(expected_score),
                    float(actual_score),
                    json.dumps(features or {}, ensure_ascii=False),
                    int(metrics.get("views", 0) or 0),
                    int(metrics.get("clicks", 0) or 0),
                    int(metrics.get("subscribers", 0) or 0),
                    float(metrics.get("revenue", 0.0) or 0.0),
                ),
            )
            conn.commit()
            _log.info("recorded_content_feedback", extra={"content_id": content_id})
    except Exception as exc:  # noqa: BLE001
        _log.error("record_content_feedback_failed", extra={"error": str(exc)})


def get_recent_feedback(limit: int = 200) -> list[dict[str, Any]]:
    """Return recent feedback records (newest first), features JSON-decoded."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM content_feedback ORDER BY created_at DESC, id DESC LIMIT ?",
                (limit,),
            )
            rows = cursor.fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            rec = dict(row)
            try:
                rec["features"] = json.loads(rec["features"]) if rec["features"] else {}
            except (json.JSONDecodeError, TypeError):
                rec["features"] = {}
            out.append(rec)
        return out
    except Exception as exc:  # noqa: BLE001
        _log.error("get_recent_feedback_failed", extra={"error": str(exc)})
        return []


def feedback_totals() -> dict[str, float]:
    """Aggregate totals across all feedback records for the OS dashboard."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            row = cursor.execute("""
                SELECT COUNT(*), COALESCE(SUM(revenue), 0), COALESCE(SUM(subscribers), 0),
                       COALESCE(SUM(views), 0), COALESCE(SUM(clicks), 0)
                FROM content_feedback
                """).fetchone()
        return {
            "samples": int(row[0]),
            "revenue": float(row[1]),
            "subscribers": int(row[2]),
            "views": int(row[3]),
            "clicks": int(row[4]),
        }
    except Exception as exc:  # noqa: BLE001
        _log.error("feedback_totals_failed", extra={"error": str(exc)})
        return {"samples": 0, "revenue": 0.0, "subscribers": 0, "views": 0, "clicks": 0}


def save_weights(weights: dict[str, float]) -> None:
    """Upsert calibrated opportunity-score weights."""
    if not weights:
        return
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.executemany(
                """
                INSERT INTO weights_state (component, weight, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(component) DO UPDATE SET
                    weight = excluded.weight, updated_at = CURRENT_TIMESTAMP
                """,
                [(comp, float(val)) for comp, val in weights.items()],
            )
            conn.commit()
            _log.info("saved_weights_state", extra={"count": len(weights)})
    except Exception as exc:  # noqa: BLE001
        _log.error("save_weights_failed", extra={"error": str(exc)})


def load_weights() -> dict[str, float]:
    """Return calibrated weights stored by the feedback loop (empty if none)."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            rows = cursor.execute("SELECT component, weight FROM weights_state").fetchall()
        return {str(comp): float(val) for comp, val in rows}
    except Exception as exc:  # noqa: BLE001
        _log.error("load_weights_failed", extra={"error": str(exc)})
        return {}


def record_cost(source: str, usd: float) -> None:
    """Append a cost event (USD) to the ledger for ROI tracking."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT INTO cost_events (source, usd) VALUES (?, ?)", (source, float(usd))
            )
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        _log.error("record_cost_failed", extra={"error": str(exc)})


def cost_total() -> float:
    """Return the total recorded cost (USD)."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            row = conn.execute("SELECT COALESCE(SUM(usd), 0) FROM cost_events").fetchone()
        return float(row[0])
    except Exception as exc:  # noqa: BLE001
        _log.error("cost_total_failed", extra={"error": str(exc)})
        return 0.0


# --- generated content assets (YouTube scripts, etc.) -----------------------


def save_generated_content(content: dict[str, Any]) -> str:
    """Upsert a generated content asset (INSERT OR REPLACE on content_id).

    ``content_id`` is taken from the dict or derived from format+title. The full
    content object is stored as JSON in ``payload``. Returns the content_id.
    """
    content_id = str(
        content.get("content_id")
        or f"{content.get('format', 'content')}:{abs(hash(content.get('title', '')))}"
    )
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO generated_content
                    (content_id, format, platform, title, body, payload)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    content_id,
                    content.get("format", ""),
                    content.get("platform", ""),
                    content.get("title", ""),
                    content.get("body", ""),
                    json.dumps(content, ensure_ascii=False),
                ),
            )
            conn.commit()
            _log.info("saved_generated_content", extra={"content_id": content_id})
    except Exception as exc:  # noqa: BLE001
        _log.error("save_generated_content_failed", extra={"error": str(exc)})
    return content_id


def get_generated_content(content_id: str) -> dict[str, Any] | None:
    """Return one generated content asset by id (payload JSON-decoded)."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT payload FROM generated_content WHERE content_id = ?", (content_id,)
            ).fetchone()
        if not row:
            return None
        return json.loads(row["payload"])
    except Exception as exc:  # noqa: BLE001
        _log.error("get_generated_content_failed", extra={"id": content_id, "error": str(exc)})
        return None


def list_generated_content(limit: int = 50) -> list[dict[str, Any]]:
    """Return recent generated content metadata (newest first, no payload)."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT content_id, format, platform, title, created_at
                FROM generated_content
                ORDER BY created_at DESC, rowid DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as exc:  # noqa: BLE001
        _log.error("list_generated_content_failed", extra={"error": str(exc)})
        return []


# --- deployments + weights history (Phase 7) --------------------------------


def record_deployment(content_id: str, platform: str, url: str, status: str) -> None:
    """Append a deployment record (virtual or real publish)."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT INTO deployments (content_id, platform, url, status) VALUES (?, ?, ?, ?)",
                (content_id, platform, url, status),
            )
            conn.commit()
            _log.info("recorded_deployment", extra={"content_id": content_id, "platform": platform})
    except Exception as exc:  # noqa: BLE001
        _log.error("record_deployment_failed", extra={"error": str(exc)})


def get_deployments(limit: int = 100) -> list[dict[str, Any]]:
    """Return recent deployment records (newest first)."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT content_id, platform, url, status, created_at
                FROM deployments ORDER BY created_at DESC, id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception as exc:  # noqa: BLE001
        _log.error("get_deployments_failed", extra={"error": str(exc)})
        return []


def deployment_mix() -> list[dict[str, Any]]:
    """Return deployment counts grouped by platform (descending)."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute(
                "SELECT platform, COUNT(*) FROM deployments GROUP BY platform ORDER BY 2 DESC"
            ).fetchall()
        return [{"platform": p, "count": int(c)} for p, c in rows]
    except Exception as exc:  # noqa: BLE001
        _log.error("deployment_mix_failed", extra={"error": str(exc)})
        return []


def record_weights_snapshot(weights: dict[str, float]) -> None:
    """Append a JSON snapshot of the calibrated weights for trend charting."""
    if not weights:
        return
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                "INSERT INTO weights_history (weights) VALUES (?)",
                (json.dumps(weights, ensure_ascii=False),),
            )
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        _log.error("record_weights_snapshot_failed", extra={"error": str(exc)})


def get_weights_history(limit: int = 50) -> list[dict[str, Any]]:
    """Return recent calibrated-weights snapshots (oldest first for charting)."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT weights, created_at FROM weights_history ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for r in reversed(rows):  # chronological order
            try:
                out.append({"weights": json.loads(r["weights"]), "created_at": r["created_at"]})
            except (json.JSONDecodeError, TypeError):
                continue
        return out
    except Exception as exc:  # noqa: BLE001
        _log.error("get_weights_history_failed", extra={"error": str(exc)})
        return []
