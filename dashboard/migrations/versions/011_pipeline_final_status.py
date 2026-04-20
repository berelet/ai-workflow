"""add final_task_status to pipeline templates and definitions

Revision ID: 011
Revises: 010
Create Date: 2026-04-05
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("global_pipeline_templates",
                  sa.Column("final_task_status", sa.String(20), nullable=False, server_default="done"))
    op.add_column("pipeline_definitions",
                  sa.Column("final_task_status", sa.String(20), nullable=False, server_default="done"))


def downgrade() -> None:
    op.drop_column("pipeline_definitions", "final_task_status")
    op.drop_column("global_pipeline_templates", "final_task_status")
