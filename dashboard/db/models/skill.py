import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, Text, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from dashboard.db.base import Base


class Skill(Base):
    __tablename__ = "skills"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    source: Mapped[str] = mapped_column(String(200), nullable=False)  # cisco/software-security
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    agent_scope: Mapped[str] = mapped_column(String(30), nullable=False, server_default="global")  # global, pm_review, ba_review, dev_review, qa_review, perf
    skill_path: Mapped[str] = mapped_column(String(500), nullable=False)  # relative path to SKILL.md
    content_md: Mapped[str | None] = mapped_column(Text, nullable=True)  # cached content of SKILL.md
    is_installed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
