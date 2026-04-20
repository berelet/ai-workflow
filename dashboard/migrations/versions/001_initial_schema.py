"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-04-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- users ---
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(320), unique=True, nullable=False, index=True),
        sa.Column("password_hash", sa.String(72), nullable=False),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("lang", sa.String(5), nullable=False, server_default="uk"),
        sa.Column("is_superadmin", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_blocked", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # --- projects ---
    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(100), unique=True, nullable=False, index=True),
        sa.Column("prefix", sa.String(4), unique=True, nullable=False, index=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("stack", sa.Text, server_default=""),
        sa.Column("visibility", sa.String(20), nullable=False, server_default="public"),
        sa.Column("repo_url", sa.String(500), nullable=True),
        sa.Column("repo_path", sa.String(500), nullable=True),
        sa.Column("task_counter", sa.Integer, nullable=False, server_default="0"),
        sa.Column("merge_strategy", sa.String(20), nullable=False, server_default="merge"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # --- project_memberships ---
    op.create_table(
        "project_memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("role", sa.String(20), nullable=False, server_default="viewer"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "project_id", name="uq_membership_user_project"),
    )

    # --- ssh_keys ---
    op.create_table(
        "ssh_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("encrypted_private_key", sa.Text, nullable=False),
        sa.Column("public_key_fingerprint", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # --- dashboard_instances ---
    op.create_table(
        "dashboard_instances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("hostname", sa.String(200), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # --- instance_project_bindings ---
    op.create_table(
        "instance_project_bindings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("instance_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("dashboard_instances.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("local_path", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("instance_id", "project_id", name="uq_instance_project"),
    )

    # --- backlog_items ---
    op.create_table(
        "backlog_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("sequence_number", sa.Integer, nullable=False),
        sa.Column("task_id_display", sa.String(20), nullable=False, index=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("priority", sa.String(20), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(20), nullable=False, server_default="backlog"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_backlog_project_status", "backlog_items", ["project_id", "status"])

    # --- backlog_item_images ---
    op.create_table(
        "backlog_item_images",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("backlog_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("backlog_items.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("storage_type", sa.String(10), nullable=False, server_default="s3"),
        sa.Column("s3_key", sa.String(500), nullable=True),
        sa.Column("local_path", sa.String(500), nullable=True),
        sa.Column("original_filename", sa.String(300), nullable=False),
        sa.Column("mime_type", sa.String(100), server_default="image/png"),
        sa.Column("size_bytes", sa.BigInteger, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # --- pipeline_definitions ---
    op.create_table(
        "pipeline_definitions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("graph_json", postgresql.JSONB, nullable=False),
        sa.Column("stages_order", postgresql.JSONB, nullable=False),
        sa.Column("discovery_stages", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # --- pipeline_runs ---
    op.create_table(
        "pipeline_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("pipeline_def_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("pipeline_definitions.id"), nullable=False),
        sa.Column("backlog_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("backlog_items.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("current_stage", sa.String(30), nullable=True),
        sa.Column("current_node_id", sa.String(20), nullable=True),
        sa.Column("auto_advance", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("git_branch", sa.String(200), nullable=True),
        sa.Column("started_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("claude_session_id", sa.String(100), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_code", sa.Integer, nullable=True),
        sa.Column("cost_usd", sa.Numeric(10, 4), nullable=True),
    )

    # --- pipeline_stage_logs ---
    op.create_table(
        "pipeline_stage_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("node_id", sa.String(20), nullable=False),
        sa.Column("stage", sa.String(30), nullable=False),
        sa.Column("node_type", sa.String(20), nullable=False, server_default="agent"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("agent", sa.String(50), nullable=True),
        sa.Column("terminal_session_id", sa.String(20), nullable=True),
        sa.Column("claude_session_id", sa.String(100), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("output_summary", sa.Text, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("return_reason", sa.Text, nullable=True),
        sa.Column("return_target_node_id", sa.String(20), nullable=True),
    )
    op.create_index("ix_stage_log_run", "pipeline_stage_logs", ["run_id"])

    # --- artifacts ---
    op.create_table(
        "artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("backlog_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("backlog_items.id"), nullable=True, index=True),
        sa.Column("stage", sa.String(30), nullable=True),
        sa.Column("artifact_type", sa.String(30), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("content_text", sa.Text, nullable=True),
        sa.Column("s3_key", sa.String(500), nullable=True),
        sa.Column("local_path", sa.String(500), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB, nullable=True),
        sa.Column("mime_type", sa.String(100), nullable=True),
        sa.Column("size_bytes", sa.BigInteger, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_artifact_project_task", "artifacts", ["project_id", "backlog_item_id"])

    # --- agent_configs ---
    op.create_table(
        "agent_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True),
        sa.Column("agent_name", sa.String(50), nullable=False),
        sa.Column("instructions_md", sa.Text, nullable=False),
        sa.Column("is_override", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("project_id", "agent_name", name="uq_agent_config_project_agent"),
    )

    # --- skills ---
    op.create_table(
        "skills",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("source", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("agent_scope", sa.String(30), nullable=False, server_default="global"),
        sa.Column("skill_path", sa.String(500), nullable=False),
        sa.Column("content_md", sa.Text, nullable=True),
        sa.Column("is_installed", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("version", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # --- system_config ---
    op.create_table(
        "system_config",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("system_config")
    op.drop_table("skills")
    op.drop_table("agent_configs")
    op.drop_index("ix_artifact_project_task", table_name="artifacts")
    op.drop_table("artifacts")
    op.drop_index("ix_stage_log_run", table_name="pipeline_stage_logs")
    op.drop_table("pipeline_stage_logs")
    op.drop_table("pipeline_runs")
    op.drop_table("pipeline_definitions")
    op.drop_table("backlog_item_images")
    op.drop_index("ix_backlog_project_status", table_name="backlog_items")
    op.drop_table("backlog_items")
    op.drop_table("instance_project_bindings")
    op.drop_table("dashboard_instances")
    op.drop_table("ssh_keys")
    op.drop_table("project_memberships")
    op.drop_table("projects")
    op.drop_table("users")
