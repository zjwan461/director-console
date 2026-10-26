"""agent_threads.context_json：跨轮次的会话上下文

Revision ID: 0012_agent_thread_context
Revises: 0011_ai_edit_runs
"""
from alembic import op
import sqlalchemy as sa

revision = "0012_agent_thread_context"
down_revision = "0011_ai_edit_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_threads", sa.Column("context_json", sa.Text, nullable=False, server_default="{}"))


def downgrade() -> None:
    op.drop_column("agent_threads", "context_json")
