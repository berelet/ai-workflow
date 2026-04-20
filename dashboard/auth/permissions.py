import uuid

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dashboard.auth.middleware import get_current_user
from dashboard.db.engine import get_db
from dashboard.db.models.user import User
from dashboard.db.models.project import Project, ProjectMembership

ROLE_RANK = {"viewer": 0, "developer": 1, "editor": 2, "owner": 3}


async def _resolve_project(db: AsyncSession, identifier: str) -> Project | None:
    """Resolve project by slug or UUID."""
    try:
        project_uuid = uuid.UUID(identifier)
        result = await db.execute(select(Project).where(Project.id == project_uuid))
    except ValueError:
        result = await db.execute(select(Project).where(Project.slug == identifier))
    return result.scalar_one_or_none()


async def _get_membership(db: AsyncSession, user_id: uuid.UUID, project_id: uuid.UUID) -> ProjectMembership | None:
    result = await db.execute(
        select(ProjectMembership).where(
            ProjectMembership.user_id == user_id,
            ProjectMembership.project_id == project_id,
        )
    )
    return result.scalar_one_or_none()


async def check_project_access(
    db: AsyncSession,
    user: User,
    project: Project,
    min_role: str = "viewer",
) -> str | None:
    """Check user access to project. Returns actual role or None.

    Logic:
    1. Check explicit membership -> return membership.role if >= min_role
    2. If no membership AND project.visibility == "public" AND min_role == "viewer":
       -> return "viewer" (implicit)
    3. Otherwise -> None (no access)

    Superadmin has NO bypass. Superadmin is checked by the same rules.
    """
    membership = await _get_membership(db, user.id, project.id)
    if membership:
        if ROLE_RANK.get(membership.role, -1) >= ROLE_RANK.get(min_role, 0):
            return membership.role
        return None
    # No membership — public projects grant implicit viewer access
    if project.visibility == "public" and min_role == "viewer":
        return "viewer"
    return None


async def require_project_access_or_raise(
    db: AsyncSession,
    user: User,
    project: Project,
    min_role: str = "viewer",
) -> str:
    """Check access and raise HTTPException if denied. Returns effective role.

    Inlines the membership check to avoid a duplicate DB query on the deny path.
    """
    membership = await _get_membership(db, user.id, project.id)
    if membership:
        if ROLE_RANK.get(membership.role, -1) >= ROLE_RANK.get(min_role, 0):
            return membership.role
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient role for this action",
        )
    # No membership — public projects grant implicit viewer
    if project.visibility == "public" and min_role == "viewer":
        return "viewer"
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Not a project member",
    )


class RequireProjectRole:
    """FastAPI dependency that checks user has at minimum the given role on a project.

    Usage in route:
        auth: tuple[User, Project] = Depends(require_editor)
    """

    def __init__(self, min_role: str = "viewer"):
        self.min_role = min_role

    async def __call__(
        self,
        name: str,
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> tuple[User, Project]:
        project = await _resolve_project(db, name)
        if not project:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

        await require_project_access_or_raise(db, user, project, self.min_role)
        return user, project


require_viewer = RequireProjectRole("viewer")
require_developer = RequireProjectRole("developer")
require_editor = RequireProjectRole("editor")
require_owner = RequireProjectRole("owner")


async def require_superadmin(user: User = Depends(get_current_user)) -> User:
    """Dependency that ensures the user is a superadmin."""
    if not user.is_superadmin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Superadmin required")
    return user
