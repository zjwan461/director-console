"""成片导出任务表

Revision ID: 0004_renders
Revises: 0003_settings
Create Date: 2026-10-19
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0004_renders"
down_revision = "0003_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "renders",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("progress", sa.Float(), server_default="0"),
        sa.Column("message", sa.Text(), server_default=""),
        sa.Column("shot_ids", sa.Text(), server_default="[]"),
        sa.Column("options", sa.Text(), server_default="{}"),
        sa.Column("output_path", sa.Text(), server_default=""),
        sa.Column("cover_path", sa.Text(), server_default=""),
        sa.Column("error", sa.Text(), server_default=""),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("started_at", sa.Float(), server_default="0"),
        sa.Column("finished_at", sa.Float(), server_default="0"),
    )
    op.create_index("idx_renders_project", "renders", ["project_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_renders_project", table_name="renders")
    op.drop_table("renders")
