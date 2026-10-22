"""renders.duration：成片时长

Revision ID: 0009_render_duration
Revises: 0008_render_shots_burned
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_render_duration"
down_revision = "0008_render_shots_burned"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("renders", sa.Column("duration", sa.Float, nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("renders", "duration")
