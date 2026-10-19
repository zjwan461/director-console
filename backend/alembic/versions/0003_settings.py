"""新增运行时设置表（ComfyUI 地址、令牌等可在页面改）

Revision ID: 0003_settings
Revises: 0002_shot_values
Create Date: 2026-10-19
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_settings"
down_revision = "0002_shot_values"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "settings",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", sa.Text(), server_default=""),
        sa.Column("updated_at", sa.Float(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("settings")
