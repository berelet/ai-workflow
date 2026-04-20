import uuid
from datetime import datetime
from sqlalchemy import String, Integer, BigInteger, Text, DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from dashboard.db.base import Base


class BacklogItem(Base):
    __tablename__ = "backlog_items"
    __table_args__ = (
        Index("ix_backlog_project_status", "project_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    task_id_display: Mapped[str] = mapped_column(String(30), nullable=False, index=True)  # AWF-1 or AWF-a3f8b2c1
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    priority: Mapped[str] = mapped_column(String(20), nullable=False, server_default="medium")  # low, medium, high
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="backlog")  # backlog, todo, in-progress, done, archived
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    project = relationship("Project", back_populates="backlog_items")
    images = relationship("BacklogItemImage", back_populates="backlog_item", cascade="all, delete-orphan")
    artifacts = relationship("Artifact", back_populates="backlog_item", cascade="all, delete")


class BacklogItemImage(Base):
    __tablename__ = "backlog_item_images"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    backlog_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("backlog_items.id", ondelete="CASCADE"), nullable=False, index=True)
    storage_type: Mapped[str] = mapped_column(String(10), nullable=False, server_default="s3")  # s3, local
    s3_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    local_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    original_filename: Mapped[str] = mapped_column(String(300), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False, server_default="image/png")
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    backlog_item = relationship("BacklogItem", back_populates="images")
