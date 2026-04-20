import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from dashboard.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(72), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    lang: Mapped[str] = mapped_column(String(5), nullable=False, server_default="uk")
    is_superadmin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_blocked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    memberships = relationship("ProjectMembership", back_populates="user", cascade="all, delete-orphan")
    ssh_keys = relationship("SSHKey", back_populates="user", cascade="all, delete-orphan")
    join_requests = relationship("JoinRequest", foreign_keys="JoinRequest.user_id", back_populates="user", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")
