"""Per-dashboard-instance project path resolution.

When multiple dashboard instances connect to the same DB, each instance has
its own filesystem and may host the same logical project at a different path.
The `instance_project_bindings` table maps (instance_id, project_id) → local_path.

This module is the SOURCE OF TRUTH for `where does this project live on disk
on the current dashboard instance`. The legacy `Project.repo_path` column is
kept as a fallback for projects that haven't been migrated yet.

Read path:
    1. Look up InstanceProjectBinding for (current DASHBOARD_UUID, project.id)
    2. If found → return its local_path
    3. Else → fall back to project.repo_path (legacy)
    4. Else → None (project has no on-disk presence on this instance)

Write path:
    Always upsert InstanceProjectBinding for the current instance. Never write
    to Project.repo_path from new code paths.
"""
import logging
import os
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dashboard.db.models.dashboard_instance import InstanceProjectBinding

if TYPE_CHECKING:
    from dashboard.db.models.project import Project

logger = logging.getLogger("services.instance_paths")


def get_current_instance_id() -> uuid.UUID | None:
    """Read DASHBOARD_UUID from env. Returns None if not set or malformed."""
    raw = os.environ.get("DASHBOARD_UUID", "").strip()
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        logger.warning("DASHBOARD_UUID env var is not a valid UUID: %r", raw)
        return None


async def resolve_local_path(db: AsyncSession, project: "Project") -> str | None:
    """Return on-disk path for `project` on the current dashboard instance.

    Looks up the binding first, falls back to legacy Project.repo_path.
    """
    instance_id = get_current_instance_id()
    if instance_id is not None and project.id is not None:
        result = await db.execute(
            select(InstanceProjectBinding.local_path).where(
                InstanceProjectBinding.instance_id == instance_id,
                InstanceProjectBinding.project_id == project.id,
            )
        )
        bound = result.scalar_one_or_none()
        if bound:
            return bound
    # Legacy fallback (pre-binding projects)
    return project.repo_path


async def set_local_path(
    db: AsyncSession,
    project_id: uuid.UUID,
    local_path: str,
) -> None:
    """Upsert the local_path binding for the current dashboard instance.

    Caller is responsible for committing the session.
    """
    instance_id = get_current_instance_id()
    if instance_id is None:
        logger.warning("set_local_path called but DASHBOARD_UUID is not set; skipping")
        return

    existing = (await db.execute(
        select(InstanceProjectBinding).where(
            InstanceProjectBinding.instance_id == instance_id,
            InstanceProjectBinding.project_id == project_id,
        )
    )).scalar_one_or_none()

    if existing:
        existing.local_path = local_path
    else:
        db.add(InstanceProjectBinding(
            instance_id=instance_id,
            project_id=project_id,
            local_path=local_path,
        ))


async def unset_local_path(db: AsyncSession, project_id: uuid.UUID) -> None:
    """Remove the binding for the current dashboard instance (used on project delete)."""
    instance_id = get_current_instance_id()
    if instance_id is None:
        return
    existing = (await db.execute(
        select(InstanceProjectBinding).where(
            InstanceProjectBinding.instance_id == instance_id,
            InstanceProjectBinding.project_id == project_id,
        )
    )).scalar_one_or_none()
    if existing:
        await db.delete(existing)


async def get_all_bindings_for_instance(db: AsyncSession) -> dict[uuid.UUID, str]:
    """Return a {project_id: local_path} map for the current instance.

    Used by /api/bootstrap to send all bindings in one query.
    """
    instance_id = get_current_instance_id()
    if instance_id is None:
        return {}
    result = await db.execute(
        select(InstanceProjectBinding.project_id, InstanceProjectBinding.local_path)
        .where(InstanceProjectBinding.instance_id == instance_id)
    )
    return {row[0]: row[1] for row in result.all()}
