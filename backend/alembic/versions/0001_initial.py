"""初始结构：项目 / 镜头 / 素材 / 任务

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-19
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("style", sa.Text(), server_default=""),
        sa.Column("notes", sa.Text(), server_default=""),
        sa.Column("created_at", sa.Float(), nullable=False),
    )

    op.create_table(
        "shots",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("idx", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("title", sa.Text(), server_default=""),
        sa.Column("preset_id", sa.Text(), server_default=""),
        sa.Column("prompt", sa.Text(), server_default=""),
        sa.Column("cover", sa.Text(), server_default=""),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
    )
    op.create_index("idx_shots_project", "shots", ["project_id", "idx"])

    op.create_table(
        "assets",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("comfy_name", sa.Text(), server_default=""),
        sa.Column("width", sa.Integer(), server_default="0"),
        sa.Column("height", sa.Integer(), server_default="0"),
        sa.Column("size", sa.Integer(), server_default="0"),
        sa.Column("meta", sa.Text(), server_default="{}"),
        sa.Column("created_at", sa.Float(), nullable=False),
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("project_id", sa.Text(), server_default=""),
        sa.Column("shot_id", sa.Text(), server_default=""),
        sa.Column("preset_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("progress", sa.Float(), server_default="0"),
        sa.Column("message", sa.Text(), server_default=""),
        sa.Column("comfy_prompt_id", sa.Text(), server_default=""),
        sa.Column("inputs", sa.Text(), server_default="{}"),
        sa.Column("outputs", sa.Text(), server_default="[]"),
        sa.Column("error", sa.Text(), server_default=""),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("started_at", sa.Float(), server_default="0"),
        sa.Column("finished_at", sa.Float(), server_default="0"),
    )
    op.create_index("idx_jobs_created", "jobs", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_jobs_created", table_name="jobs")
    op.drop_table("jobs")
    op.drop_table("assets")
    op.drop_index("idx_shots_project", table_name="shots")
    op.drop_table("shots")
    op.drop_table("projects")
