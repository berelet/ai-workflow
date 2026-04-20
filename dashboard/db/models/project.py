import uuid
from datetime import datetime
from sqlalchemy import String, Integer, Text, Boolean, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from dashboard.db.base import Base


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    prefix: Mapped[str] = mapped_column(String(4), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    stack: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, server_default="public")  # public, private
    repo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    repo_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    base_branch: Mapped[str] = mapped_column(String(100), nullable=False, server_default="main")
    task_counter: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    merge_strategy: Mapped[str] = mapped_column(String(20), nullable=False, server_default="merge")  # merge, pr
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    memberships = relationship("ProjectMembership", back_populates="project", cascade="all, delete-orphan")
    backlog_items = relationship("BacklogItem", back_populates="project", cascade="all, delete-orphan")
    pipeline_definitions = relationship("PipelineDefinition", back_populates="project", cascade="all, delete-orphan")
    pipeline_runs = relationship("PipelineRun", back_populates="project", cascade="all, delete-orphan")
    artifacts = relationship("Artifact", back_populates="project", cascade="all, delete-orphan")
    agent_configs = relationship("AgentConfig", back_populates="project", cascade="all, delete-orphan")
    join_requests = relationship("JoinRequest", back_populates="project", cascade="all, delete-orphan")


class ProjectMembership(Base):
    __tablename__ = "project_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "project_id", name="uq_membership_user_project"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, server_default="viewer")  # owner, editor, viewer
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user = relationship("User", back_populates="memberships")
    project = relationship("Project", back_populates="memberships")
