import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Integer, Boolean, Numeric, Text, DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from dashboard.db.base import Base


class GlobalPipelineTemplate(Base):
    """System-wide pipeline template managed by superadmin.
    Copied to projects on creation. Only one can be is_active=True."""
    __tablename__ = "global_pipeline_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    graph_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    stages_order: Mapped[list] = mapped_column(JSONB, nullable=False)
    discovery_stages: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    final_task_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="done")  # done, todo
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class PipelineDefinition(Base):
    __tablename__ = "pipeline_definitions"
    __table_args__ = (
        Index("ix_pipeline_def_project", "project_id"),
        Index("uq_pipeline_def_default", "project_id", unique=True, postgresql_where="is_default = true"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    graph_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    stages_order: Mapped[list] = mapped_column(JSONB, nullable=False)  # ["PM","PM_REVIEW",...]
    discovery_stages: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    final_task_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="done")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    project = relationship("Project", back_populates="pipeline_definitions")


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    pipeline_def_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("pipeline_definitions.id", ondelete="CASCADE"), nullable=False)
    backlog_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("backlog_items.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")  # pending, running, completed, failed, cancelled
    current_stage: Mapped[str | None] = mapped_column(String(30), nullable=True)
    current_node_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    auto_advance: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    git_branch: Mapped[str | None] = mapped_column(String(200), nullable=True)
    started_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    claude_session_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)

    project = relationship("Project", back_populates="pipeline_runs")
    pipeline_definition = relationship("PipelineDefinition")
    backlog_item = relationship("BacklogItem")
    started_by_user = relationship("User", foreign_keys=[started_by])
    stage_logs = relationship("PipelineStageLog", back_populates="pipeline_run", cascade="all, delete-orphan")


class PipelineStageLog(Base):
    __tablename__ = "pipeline_stage_logs"
    __table_args__ = (
        Index("ix_stage_log_run", "run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False)
    node_id: Mapped[str] = mapped_column(String(20), nullable=False)
    stage: Mapped[str] = mapped_column(String(30), nullable=False)  # PM, BA, DEV, etc.
    node_type: Mapped[str] = mapped_column(String(20), nullable=False, server_default="agent")  # agent, reviewer
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")  # pending, running, completed, failed, returned, skipped
    agent: Mapped[str | None] = mapped_column(String(50), nullable=True)  # project-manager, etc.
    terminal_session_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    claude_session_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    output_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    return_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    return_target_node_id: Mapped[str | None] = mapped_column(String(20), nullable=True)

    pipeline_run = relationship("PipelineRun", back_populates="stage_logs")
