"""fix cascades, partial unique index, column widths

Revision ID: 002
Revises: 001
Create Date: 2026-04-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Fix CASCADE on artifacts.backlog_item_id
    op.drop_constraint("artifacts_backlog_item_id_fkey", "artifacts", type_="foreignkey")
    op.create_foreign_key(
        "artifacts_backlog_item_id_fkey", "artifacts",
        "backlog_items", ["backlog_item_id"], ["id"], ondelete="CASCADE"
    )

    # 2. Fix CASCADE on pipeline_runs.pipeline_def_id
    op.drop_constraint("pipeline_runs_pipeline_def_id_fkey", "pipeline_runs", type_="foreignkey")
    op.create_foreign_key(
        "pipeline_runs_pipeline_def_id_fkey", "pipeline_runs",
        "pipeline_definitions", ["pipeline_def_id"], ["id"], ondelete="CASCADE"
    )

    # 3. Fix CASCADE on pipeline_runs.backlog_item_id
    op.drop_constraint("pipeline_runs_backlog_item_id_fkey", "pipeline_runs", type_="foreignkey")
    op.create_foreign_key(
        "pipeline_runs_backlog_item_id_fkey", "pipeline_runs",
        "backlog_items", ["backlog_item_id"], ["id"], ondelete="CASCADE"
    )

    # 4. Add partial unique index on pipeline_definitions (one default per project)
    op.execute(
        "CREATE UNIQUE INDEX uq_pipeline_def_default ON pipeline_definitions (project_id) WHERE is_default = true"
    )

    # 5. Widen task_id_display from VARCHAR(20) to VARCHAR(30)
    op.alter_column("backlog_items", "task_id_display", type_=sa.String(30))

    # 6. Add index on projects.created_by
    op.create_index("ix_projects_created_by", "projects", ["created_by"])


def downgrade() -> None:
    op.drop_index("ix_projects_created_by", table_name="projects")
    op.alter_column("backlog_items", "task_id_display", type_=sa.String(20))
    op.drop_index("uq_pipeline_def_default", table_name="pipeline_definitions")

    op.drop_constraint("pipeline_runs_backlog_item_id_fkey", "pipeline_runs", type_="foreignkey")
    op.create_foreign_key(
        "pipeline_runs_backlog_item_id_fkey", "pipeline_runs",
        "backlog_items", ["backlog_item_id"], ["id"]
    )
    op.drop_constraint("pipeline_runs_pipeline_def_id_fkey", "pipeline_runs", type_="foreignkey")
    op.create_foreign_key(
        "pipeline_runs_pipeline_def_id_fkey", "pipeline_runs",
        "pipeline_definitions", ["pipeline_def_id"], ["id"]
    )
    op.drop_constraint("artifacts_backlog_item_id_fkey", "artifacts", type_="foreignkey")
    op.create_foreign_key(
        "artifacts_backlog_item_id_fkey", "artifacts",
        "backlog_items", ["backlog_item_id"], ["id"]
    )
