"""Admin graph persistence tables (Phase 9).

Adds dedicated ``graph_nodes`` / ``graph_edges`` tables backing the live admin
graph view (see ``database/repositories/graph_repo.py``). Kept separate from the
``nodes`` / ``edges`` tables in migration 001 so the admin graph feature is
isolated and schema-consistent across SQLite (dev) and PostgreSQL (prod).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "graph_nodes",
        sa.Column("node_id", sa.String(128), primary_key=True),
        sa.Column("type", sa.String(32), server_default="topic"),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("weight", sa.Float, server_default="1.0"),
    )
    op.create_index("ix_graph_nodes_type", "graph_nodes", ["type"])

    op.create_table(
        "graph_edges",
        sa.Column("edge_id", sa.String(256), primary_key=True),
        sa.Column("from_node", sa.String(128), nullable=False),
        sa.Column("to_node", sa.String(128), nullable=False),
        sa.Column("relation_type", sa.String(32), server_default="related_to"),
        sa.Column("weight", sa.Float, server_default="0.5"),
    )
    op.create_index("ix_graph_edges_from", "graph_edges", ["from_node"])
    op.create_index("ix_graph_edges_to", "graph_edges", ["to_node"])


def downgrade() -> None:
    op.drop_table("graph_edges")
    op.drop_table("graph_nodes")
