"""fix nullable columns and add global agent config unique index

Revision ID: 003
Revises: 002
Create Date: 2026-04-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # B1: Fix nullable=False on columns that had implicit nullable in migration 001
    # Set empty string default first for any existing NULLs, then make NOT NULL
    op.execute("UPDATE projects SET description = '' WHERE description IS NULL")
    op.execute("UPDATE projects SET stack = '' WHERE stack IS NULL")
    op.execute("UPDATE backlog_items SET description = '' WHERE description IS NULL")
    op.execute("UPDATE backlog_item_images SET mime_type = 'image/png' WHERE mime_type IS NULL")
    op.execute("UPDATE skills SET description = '' WHERE description IS NULL")

    op.alter_column("projects", "description", nullable=False, server_default="")
    op.alter_column("projects", "stack", nullable=False, server_default="")
    op.alter_column("backlog_items", "description", nullable=False, server_default="")
    op.alter_column("backlog_item_images", "mime_type", nullable=False, server_default="image/png")
    op.alter_column("skills", "description", nullable=False, server_default="")

    # H5: Partial unique index for global agent configs (project_id IS NULL)
    op.execute(
        "CREATE UNIQUE INDEX uq_agent_config_global ON agent_configs (agent_name) WHERE project_id IS NULL"
    )


def downgrade() -> None:
    op.drop_index("uq_agent_config_global", table_name="agent_configs")

    op.alter_column("skills", "description", nullable=True, server_default=None)
    op.alter_column("backlog_item_images", "mime_type", nullable=True, server_default=None)
    op.alter_column("backlog_items", "description", nullable=True, server_default=None)
    op.alter_column("projects", "stack", nullable=True, server_default=None)
    op.alter_column("projects", "description", nullable=True, server_default=None)
