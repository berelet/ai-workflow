import uuid
from datetime import datetime
from sqlalchemy import String, BigInteger, Text, DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from dashboard.db.base import Base


class Artifact(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        Index("ix_artifact_project_task", "project_id", "backlog_item_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    backlog_item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("backlog_items.id", ondelete="CASCADE"), nullable=True, index=True)
    stage: Mapped[str | None] = mapped_column(String(30), nullable=True)  # PM, BA, DEV, etc.
    artifact_type: Mapped[str] = mapped_column(String(30), nullable=False)  # text, code_changes, screenshot, binary
    name: Mapped[str] = mapped_column(String(300), nullable=False)  # filename: user-stories.md, spec.md
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # for text artifacts
    s3_key: Mapped[str | None] = mapped_column(String(500), nullable=True)  # for S3-stored binaries
    local_path: Mapped[str | None] = mapped_column(String(500), nullable=True)  # for local project artifacts
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # code_changes detail, etc.
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    project = relationship("Project", back_populates="artifacts")
    backlog_item = relationship("BacklogItem", back_populates="artifacts")
