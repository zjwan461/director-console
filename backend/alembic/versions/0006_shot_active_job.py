"""shots.active_job：选定用哪一次生成

Revision ID: 0006_shot_active_job
Revises: 0005_render_shots
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_shot_active_job"
down_revision = "0005_render_shots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shots", sa.Column("active_job", sa.String(64), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("shots", "active_job")
