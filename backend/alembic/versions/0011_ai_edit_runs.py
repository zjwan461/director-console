"""ai_edit_runs：服务端 AI 剪辑批量任务的进度

Revision ID: 0011_ai_edit_runs
Revises: 0010_agent_tables
"""
from alembic import op
import sqlalchemy as sa

revision = "0011_ai_edit_runs"
down_revision = "0010_agent_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_edit_runs",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("project_id", sa.Text, nullable=False, server_default=""),
        sa.Column("status", sa.Text, nullable=False, server_default="running"),
        sa.Column("shot_ids", sa.Text, nullable=False, server_default="[]"),
        sa.Column("options_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("state_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("error", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.Float, nullable=False, server_default="0"),
        sa.Column("updated_at", sa.Float, nullable=False, server_default="0"),
    )
    op.create_index("idx_ai_edit_runs_project", "ai_edit_runs", ["project_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_ai_edit_runs_project", table_name="ai_edit_runs")
    op.drop_table("ai_edit_runs")
