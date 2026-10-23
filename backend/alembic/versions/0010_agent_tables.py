"""agent_* 表：会话、消息、运行、产物

Revision ID: 0010_agent_tables
Revises: 0009_render_duration
"""
from alembic import op
import sqlalchemy as sa

revision = "0010_agent_tables"
down_revision = "0009_render_duration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_threads",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("title", sa.Text, nullable=False, server_default="新对话"),
        sa.Column("project_id", sa.Text, nullable=False, server_default=""),
        sa.Column("model", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.Float, nullable=False, server_default="0"),
        sa.Column("updated_at", sa.Float, nullable=False, server_default="0"),
        sa.Column("archived", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("idx_agent_threads_project", "agent_threads", ["project_id", "updated_at"])

    op.create_table(
        "agent_messages",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("thread_id", sa.Text, nullable=False),
        sa.Column("run_id", sa.Text, nullable=False, server_default=""),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("content", sa.Text, nullable=False, server_default=""),
        sa.Column("parts_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("seq", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.Float, nullable=False, server_default="0"),
    )
    op.create_index("idx_agent_messages_thread", "agent_messages", ["thread_id", "seq"])

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("thread_id", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="running"),
        sa.Column("node", sa.Text, nullable=False, server_default=""),
        sa.Column("state_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("pending_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("error", sa.Text, nullable=False, server_default=""),
        sa.Column("steps", sa.Integer, nullable=False, server_default="0"),
        sa.Column("started_at", sa.Float, nullable=False, server_default="0"),
        sa.Column("finished_at", sa.Float, nullable=True),
    )
    op.create_index("idx_agent_runs_thread", "agent_runs", ["thread_id", "started_at"])

    op.create_table(
        "agent_artifacts",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("run_id", sa.Text, nullable=False, server_default=""),
        sa.Column("thread_id", sa.Text, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("ref_id", sa.Text, nullable=False, server_default=""),
        sa.Column("url", sa.Text, nullable=False, server_default=""),
        sa.Column("meta_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.Float, nullable=False, server_default="0"),
    )
    op.create_index("idx_agent_artifacts_thread", "agent_artifacts", ["thread_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_agent_artifacts_thread", table_name="agent_artifacts")
    op.drop_table("agent_artifacts")
    op.drop_index("idx_agent_runs_thread", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_index("idx_agent_messages_thread", table_name="agent_messages")
    op.drop_table("agent_messages")
    op.drop_index("idx_agent_threads_project", table_name="agent_threads")
    op.drop_table("agent_threads")
