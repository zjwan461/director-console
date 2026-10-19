"""镜头增加表单快照与末帧引用

Revision ID: 0002_shot_values
Revises: 0001_initial
Create Date: 2026-10-19
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002_shot_values"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite 不支持一次加两列以外的复杂变更，统一走 batch（内部重建表）
    with op.batch_alter_table("shots") as batch:
        batch.add_column(sa.Column("values_json", sa.Text(), server_default="{}"))
        batch.add_column(sa.Column("last_frame", sa.Text(), server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("shots") as batch:
        batch.drop_column("last_frame")
        batch.drop_column("values_json")
