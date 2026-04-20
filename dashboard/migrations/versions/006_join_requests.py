"""add join_requests table

Revision ID: 006
Revises: 005
Create Date: 2026-04-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "join_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("message", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id"), nullable=True),
    )

    # Partial unique index: only one pending request per user per project
    op.create_index(
        "uq_join_request_user_project_pending",
        "join_requests",
        ["user_id", "project_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )

    # Composite index for catalog query: WHERE visibility = 'public' ORDER BY created_at DESC
    op.create_index(
        "ix_projects_visibility_created",
        "projects",
        ["visibility", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_projects_visibility_created", table_name="projects")
    op.drop_index("uq_join_request_user_project_pending", table_name="join_requests")
    op.drop_table("join_requests")
