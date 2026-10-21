"""render_shots.burned_subtitle：视频自带字幕

Revision ID: 0008_render_shots_burned
Revises: 0007_render_shots_fit
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_render_shots_burned"
down_revision = "0007_render_shots_fit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("render_shots", sa.Column("burned_subtitle", sa.Integer, nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("render_shots", "burned_subtitle")
