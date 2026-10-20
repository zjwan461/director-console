"""render_shots：成片的逐镜编辑参数

Revision ID: 0005_render_shots
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_render_shots"
down_revision = "0004_renders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "render_shots",
        sa.Column("render_id", sa.String(64), primary_key=True),
        sa.Column("shot_id", sa.String(64), primary_key=True),
        sa.Column("idx", sa.Integer, nullable=False, server_default="0"),
        sa.Column("in_point", sa.Float, nullable=False, server_default="0"),
        sa.Column("out_point", sa.Float, nullable=True),
        sa.Column("speed", sa.Float, nullable=False, server_default="1"),
        sa.Column("volume_db", sa.Float, nullable=False, server_default="0"),
        sa.Column("muted", sa.Integer, nullable=False, server_default="0"),
        sa.Column("voice_asset", sa.String(64), nullable=False, server_default=""),
        sa.Column("subtitle", sa.Text, nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_table("render_shots")
