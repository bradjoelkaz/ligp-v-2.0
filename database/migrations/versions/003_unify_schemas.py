"""003 — unify nodes/content schemas with the raw-SQL repositories; drop dead edges.

Tech-debt cleanup (Phase 10). The Alembic ``001`` schema and the raw-SQL
repositories (``node_repo.py`` / ``content_repo.py``) had drifted into two
parallel definitions (e.g. ``label`` vs ``name``, ``embedding_path`` vs
``embedding``; the repo ``content`` table also differs from ``001``). This
migration makes the DB schema the single source of truth that MATCHES the
repositories.

- ``nodes``  : recreated with the unified columns (superset of 001 + repo).
- ``content``: recreated with the unified columns (superset of 001 + repo).
- ``edges``  : dropped — it had zero raw-SQL consumers (graph edges live in
  ``graph_edges`` via GraphRepository, created by migration 002).

Operational note: this migration DROPs and recreates ``nodes``/``content`` (the
project confirmed no production data in these tables). The graph tables
(``graph_nodes`` / ``graph_edges`` from 002) are intentionally left untouched.

The column sets below are kept in lock-step with the ``_SCHEMA`` CREATE TABLE
statements in ``database/repositories/node_repo.py`` and ``content_repo.py``
(verified by ``tests/unit/test_schema_consistency.py``).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def _create_unified_nodes() -> None:
    op.create_table(
        "nodes",
        sa.Column("node_id", sa.String(64), primary_key=True),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("name", sa.Text),
        sa.Column("weight", sa.Float, server_default="0"),
        sa.Column("embedding", sa.Text),
        sa.Column("lang", sa.String(8), server_default="ko"),
        sa.Column("graph_score", sa.Float, server_default="0"),
        sa.Column("revenue_score", sa.Float, server_default="0"),
        sa.Column("trend_state", sa.String(16), server_default="unknown"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_nodes_trend_state", "nodes", ["trend_state"])
    op.create_index("ix_nodes_graph_score", "nodes", ["graph_score"])


def _create_unified_content() -> None:
    op.create_table(
        "content",
        sa.Column("content_id", sa.String(64), primary_key=True),
        sa.Column("node_id", sa.String(64), nullable=True),
        sa.Column("platform", sa.String(32)),
        sa.Column("status", sa.String(16), server_default="draft"),
        sa.Column("title", sa.Text),
        sa.Column("body", sa.Text),
        sa.Column("payload", sa.Text),
        sa.Column("tags", sa.Text),
        sa.Column("quality_score", sa.Float),
        sa.Column("published_url", sa.Text),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("generator", sa.String(32)),
        sa.Column("llm_cost_usd", sa.Float, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_content_status", "content", ["status"])
    op.create_index("ix_content_platform", "content", ["platform"])


def upgrade() -> None:
    # No production data in these tables -> drop & recreate for a clean unify.
    op.drop_table("edges")  # dead table: zero raw-SQL consumers
    op.drop_table("content")
    op.drop_table("nodes")
    _create_unified_nodes()
    _create_unified_content()


def downgrade() -> None:
    # Restore the original 001 schemas for nodes/content and the edges table.
    op.drop_table("content")
    op.drop_table("nodes")

    op.create_table(
        "nodes",
        sa.Column("node_id", sa.String(64), primary_key=True),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("label", sa.Text, nullable=False),
        sa.Column("lang", sa.String(8), server_default="ko"),
        sa.Column("embedding_path", sa.Text, nullable=True),
        sa.Column("graph_score", sa.Float, server_default="0"),
        sa.Column("revenue_score", sa.Float, server_default="0"),
        sa.Column("trend_state", sa.String(16), server_default="unknown"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    op.create_index("ix_nodes_trend_state", "nodes", ["trend_state"])
    op.create_index("ix_nodes_graph_score", "nodes", ["graph_score"])

    op.create_table(
        "edges",
        sa.Column("edge_id", sa.String(64), primary_key=True),
        sa.Column("src", sa.String(64), sa.ForeignKey("nodes.node_id", ondelete="CASCADE")),
        sa.Column("dst", sa.String(64), sa.ForeignKey("nodes.node_id", ondelete="CASCADE")),
        sa.Column("relation", sa.String(32), nullable=False),
        sa.Column("weight", sa.Float, server_default="0.5"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_edges_src", "edges", ["src"])
    op.create_index("ix_edges_dst", "edges", ["dst"])

    op.create_table(
        "content",
        sa.Column("content_id", sa.String(64), primary_key=True),
        sa.Column(
            "node_id",
            sa.String(64),
            sa.ForeignKey("nodes.node_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), server_default="pending"),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("body", sa.Text, nullable=True),
        sa.Column("tags", sa.JSON, nullable=True),
        sa.Column("quality_score", sa.Float, nullable=True),
        sa.Column("published_url", sa.Text, nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("generator", sa.String(32), nullable=True),
        sa.Column("llm_cost_usd", sa.Float, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), onupdate=sa.func.now()),
    )
    op.create_index("ix_content_status", "content", ["status"])
    op.create_index("ix_content_platform", "content", ["platform"])
