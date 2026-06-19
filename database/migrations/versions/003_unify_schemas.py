"""003 — unify nodes/content schemas with the raw-SQL repositories; drop dead edges.

Tech-debt cleanup (Phase 10). The Alembic ``001`` schema and the raw-SQL
repositories (``node_repo.py`` / ``content_repo.py``) had drifted apart
(``label`` vs ``name``, ``embedding_path`` vs ``embedding``; the repo ``content``
also stores a ``payload`` column). This migration reconciles the DB schema to
match the repositories.

The unified schema differs from ``001`` only by a few columns, so we use
**ALTER** (not drop+recreate). This is FK-safe on PostgreSQL — ``001`` creates
``metrics``/``attribution_log`` with FKs to ``content`` and ``edges`` with FKs to
``nodes``, so dropping ``content``/``nodes`` is rejected by Postgres (Phase 15
caught this). ALTER preserves those constraints.

Changes:
- ``nodes``  : rename ``label`` -> ``name``, ``embedding_path`` -> ``embedding``;
  add ``weight`` (other unified columns already exist in 001).
- ``content``: add ``payload`` (other unified columns already exist in 001).
- ``edges``  : dropped — zero raw-SQL consumers (graph edges live in
  ``graph_edges`` from migration 002).

Untouched: ``graph_nodes`` / ``graph_edges`` (migration 002 / GraphRepository).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Dead table: nothing references 'edges', so it can be dropped directly.
    op.drop_table("edges")

    # Unify 'nodes' (FK-safe: rename/add, no drop).
    op.alter_column("nodes", "label", new_column_name="name")
    op.alter_column("nodes", "embedding_path", new_column_name="embedding")
    op.add_column("nodes", sa.Column("weight", sa.Float, server_default="0"))

    # Unify 'content' (repo stores the full item JSON in 'payload').
    op.add_column("content", sa.Column("payload", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("content", "payload")
    op.drop_column("nodes", "weight")
    op.alter_column("nodes", "embedding", new_column_name="embedding_path")
    op.alter_column("nodes", "name", new_column_name="label")

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
