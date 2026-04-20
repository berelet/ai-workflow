"""fix user FK ondelete SET NULL, fix pipeline_definitions index name

Revision ID: 004
Revises: 003
Create Date: 2026-04-02
"""
from typing import Sequence, Union

from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. backlog_items.created_by: add ondelete SET NULL
    op.drop_constraint("backlog_items_created_by_fkey", "backlog_items", type_="foreignkey")
    op.create_foreign_key(
        "backlog_items_created_by_fkey", "backlog_items",
        "users", ["created_by"], ["id"], ondelete="SET NULL"
    )

    # 2. pipeline_runs.started_by: add ondelete SET NULL
    op.drop_constraint("pipeline_runs_started_by_fkey", "pipeline_runs", type_="foreignkey")
    op.create_foreign_key(
        "pipeline_runs_started_by_fkey", "pipeline_runs",
        "users", ["started_by"], ["id"], ondelete="SET NULL"
    )

    # 3. Fix index name on pipeline_definitions.project_id
    #    Migration 001 created auto-named index via index=True on column
    op.drop_index("ix_pipeline_definitions_project_id", table_name="pipeline_definitions")
    op.create_index("ix_pipeline_def_project", "pipeline_definitions", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_pipeline_def_project", table_name="pipeline_definitions")
    op.create_index("ix_pipeline_definitions_project_id", "pipeline_definitions", ["project_id"])

    op.drop_constraint("pipeline_runs_started_by_fkey", "pipeline_runs", type_="foreignkey")
    op.create_foreign_key(
        "pipeline_runs_started_by_fkey", "pipeline_runs",
        "users", ["started_by"], ["id"]
    )

    op.drop_constraint("backlog_items_created_by_fkey", "backlog_items", type_="foreignkey")
    op.create_foreign_key(
        "backlog_items_created_by_fkey", "backlog_items",
        "users", ["created_by"], ["id"]
    )
