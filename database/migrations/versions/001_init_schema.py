"""Initial schema.

Tables: nodes, edges, content, metrics, attribution_log, experiments.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- nodes ----------------------------------------------------------------
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

    # -- edges ----------------------------------------------------------------
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

    # -- content --------------------------------------------------------------
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
    op.create_index("ix_content_published_at", "content", ["published_at"])

    # -- metrics --------------------------------------------------------------
    op.create_table(
        "metrics",
        sa.Column("metric_id", sa.String(64), primary_key=True),
        sa.Column(
            "content_id",
            sa.String(64),
            sa.ForeignKey("content.content_id", ondelete="CASCADE"),
        ),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("views", sa.BigInteger, server_default="0"),
        sa.Column("clicks", sa.BigInteger, server_default="0"),
        sa.Column("ctr", sa.Float, server_default="0"),
        sa.Column("watch_time_sec", sa.BigInteger, server_default="0"),
        sa.Column("shares", sa.Integer, server_default="0"),
        sa.Column("revenue_est", sa.Float, server_default="0"),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_metrics_content_id", "metrics", ["content_id"])

    # -- attribution_log ------------------------------------------------------
    op.create_table(
        "attribution_log",
        sa.Column("log_id", sa.String(64), primary_key=True),
        sa.Column(
            "content_id",
            sa.String(64),
            sa.ForeignKey("content.content_id", ondelete="CASCADE"),
        ),
        sa.Column("checkpoint_hours", sa.Integer, nullable=False),
        sa.Column("attributed_revenue", sa.Float, server_default="0"),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # -- experiments ----------------------------------------------------------
    op.create_table(
        "experiments",
        sa.Column("exp_id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("variants", sa.JSON, nullable=False),
        sa.Column("traffic_split", sa.JSON, nullable=False),
        sa.Column("status", sa.String(16), server_default="active"),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("results", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("experiments")
    op.drop_table("attribution_log")
    op.drop_table("metrics")
    op.drop_table("content")
    op.drop_table("edges")
    op.drop_table("nodes")
