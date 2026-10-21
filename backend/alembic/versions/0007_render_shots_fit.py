"""render_shots.fit：单镜画布适配方式

Revision ID: 0007_render_shots_fit
Revises: 0006_shot_active_job
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_render_shots_fit"
down_revision = "0006_shot_active_job"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("render_shots", sa.Column("fit", sa.String(16), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("render_shots", "fit")
