import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, Text, DateTime, ForeignKey, UniqueConstraint, Index, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from dashboard.db.base import Base


class AgentConfig(Base):
    __tablename__ = "agent_configs"
    __table_args__ = (
        UniqueConstraint("project_id", "agent_name", name="uq_agent_config_project_agent"),
        Index("uq_agent_config_global", "agent_name", unique=True, postgresql_where="project_id IS NULL"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    agent_name: Mapped[str] = mapped_column(String(50), nullable=False)  # project-manager, business-analyst, etc.
    instructions_md: Mapped[str] = mapped_column(Text, nullable=False)
    is_override: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    project = relationship("Project", back_populates="agent_configs")
