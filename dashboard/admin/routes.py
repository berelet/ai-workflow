from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from dashboard.auth.permissions import require_superadmin
from dashboard.auth.utils import hash_password_async, user_to_dict, parse_uuid
from dashboard.db.engine import get_db
from dashboard.db.models.user import User
from dashboard.db.models.project import Project

router = APIRouter(prefix="/api/admin", tags=["admin"])

MAX_PASSWORD_LENGTH = 128


# --- Schemas ---

class ResetPasswordRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=MAX_PASSWORD_LENGTH)


class SetSuperadminRequest(BaseModel):
    grant: bool


# --- Routes ---

@router.get("/users")
async def list_users(
    search: str = "",
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    include_projects: bool = Query(default=False),
    admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    query = select(User).order_by(User.created_at.desc())
    count_query = select(func.count(User.id))

    if search:
        pattern = f"%{search}%"
        where = or_(User.email.ilike(pattern), User.display_name.ilike(pattern))
        query = query.where(where)
        count_query = count_query.where(where)

    total = (await db.execute(count_query)).scalar()
    result = await db.execute(query.offset(offset).limit(limit))
    users = result.scalars().all()

    user_dicts = [user_to_dict(u, include_admin_fields=True) for u in users]

    # Inventory of projects per user (membership-based). Superadmin sees the
    # FACT a user has access to a private project (name + visibility), but
    # never the project's content — file/api endpoints still enforce membership.
    if include_projects and users:
        from dashboard.db.models.project import ProjectMembership
        user_ids = [u.id for u in users]
        rows = (await db.execute(
            select(
                ProjectMembership.user_id,
                Project.slug,
                Project.name,
                Project.visibility,
                ProjectMembership.role,
            )
            .join(Project, Project.id == ProjectMembership.project_id)
            .where(ProjectMembership.user_id.in_(user_ids))
            .order_by(Project.name)
        )).all()

        by_user: dict = {uid: [] for uid in user_ids}
        for uid, slug, name, vis, role in rows:
            by_user[uid].append({
                "slug": slug,
                "name": name,
                "visibility": vis,
                "role": role,
            })
        for ud, u in zip(user_dicts, users):
            ud["projects"] = by_user.get(u.id, [])

    return {"users": user_dicts, "total": total}


@router.post("/users/{user_id}/block")
async def toggle_block(
    user_id: str,
    admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    uid = parse_uuid(user_id, "user_id")
    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot block yourself")

    user.is_blocked = not user.is_blocked
    await db.commit()
    return {"user": user_to_dict(user, include_admin_fields=True)}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: str,
    admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    uid = parse_uuid(user_id, "user_id")
    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    # Transfer project ownership to admin before deletion
    owned_projects = await db.execute(
        select(Project).where(Project.created_by == user.id)
    )
    for project in owned_projects.scalars().all():
        project.created_by = admin.id

    await db.delete(user)
    await db.commit()
    return {"ok": True}


@router.post("/users/{user_id}/reset-password")
async def reset_password(
    user_id: str,
    body: ResetPasswordRequest,
    admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    uid = parse_uuid(user_id, "user_id")
    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.password_hash = await hash_password_async(body.new_password)
    await db.commit()
    return {"ok": True}


@router.post("/users/{user_id}/superadmin")
async def toggle_superadmin(
    user_id: str,
    body: SetSuperadminRequest,
    admin: User = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
):
    uid = parse_uuid(user_id, "user_id")
    result = await db.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id and not body.grant:
        raise HTTPException(status_code=400, detail="Cannot revoke your own superadmin")

    user.is_superadmin = body.grant
    await db.commit()
    return {"user": user_to_dict(user, include_admin_fields=True)}
