"""add base_branch column to projects, used by clone-from-git feature

Revision ID: 012
Revises: 011
Create Date: 2026-04-10

Adds Project.base_branch (default 'main') to support per-project base branch
configuration. Replaces hardcoded 'develop'/'master' in git_manager.

Backfill strategy: existing rows get 'main' default, can be edited later in
project settings. The workspaces_dir setting is stored in system_config
(key='workspaces_dir') — no schema change needed.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("base_branch", sa.String(100), nullable=False, server_default="main"),
    )


def downgrade() -> None:
    op.drop_column("projects", "base_branch")
