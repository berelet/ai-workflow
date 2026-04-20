"""Public Projects Catalog API.

Endpoints for browsing public projects, requesting to join,
and managing join requests (owner / superadmin).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from html import escape as html_escape
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import Select, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from dashboard.auth.middleware import get_current_user, get_optional_user
from dashboard.db.engine import get_db
from dashboard.db.models.join_request import JoinRequest
from dashboard.db.models.project import Project, ProjectMembership
from dashboard.db.models.user import User

router = APIRouter(tags=["catalog"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class JoinRequestCreate(BaseModel):
    message: str | None = Field(None, max_length=500)


class JoinRequestAction(BaseModel):
    action: Literal["approve", "reject"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _escape_like(value: str) -> str:
    """Escape SQL LIKE/ILIKE wildcards so they are treated as literals."""
    return (
        value
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def _member_count_subq() -> Select:
    return (
        select(func.count(ProjectMembership.id))
        .where(ProjectMembership.project_id == Project.id)
        .correlate(Project)
        .scalar_subquery()
    )


async def _get_public_project(db: AsyncSession, slug: str) -> Project:
    """Return a public project by slug or raise 404."""
    result = await db.execute(
        select(Project).where(
            Project.slug == slug,
            Project.visibility == "public",
        )
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _get_project_by_slug(db: AsyncSession, slug: str) -> Project:
    """Return a project by slug (any visibility) or raise 404.

    Used for owner/admin endpoints where the project may have been
    switched to private after join requests were submitted.
    """
    result = await db.execute(select(Project).where(Project.slug == slug))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _require_owner_or_superadmin(
    db: AsyncSession,
    user: User,
    project: Project,
) -> None:
    """Raise 403 unless the user is the project owner (by membership).

    Superadmin has no bypass — must have owner membership on the project.
    """
    from dashboard.auth.permissions import check_project_access
    role = await check_project_access(db, user, project, "owner")
    if role is None:
        raise HTTPException(status_code=403, detail="Forbidden")


def _parse_uuid(value: str) -> uuid.UUID:
    """Parse a string as UUID or raise 404."""
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail="Not found")


def _js_string(value: str) -> str:
    """Return a JS-safe string literal (with quotes) for embedding in HTML attributes.

    Uses json.dumps which handles escaping of quotes, backslashes, newlines,
    and Unicode. The result is a quoted string safe for JS contexts within
    HTML attribute values.
    """
    return json.dumps(value)


# ---------------------------------------------------------------------------
# 1. GET /api/projects/public  -  browse catalog
# ---------------------------------------------------------------------------

@router.get("/api/projects/public")
async def list_public_projects(
    request: Request,
    q: str = "",
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=50),
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    if len(q) > 200:
        raise HTTPException(status_code=422, detail="Search query too long (max 200 chars)")

    member_count = _member_count_subq()

    # Base query: only public projects
    base = select(Project).where(Project.visibility == "public")

    # Search filter
    if q.strip():
        pattern = f"%{_escape_like(q.strip())}%"
        base = base.where(
            or_(
                Project.name.ilike(pattern),
                Project.description.ilike(pattern),
                Project.stack.ilike(pattern),
            )
        )

    # Total count
    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar_one()

    # Paginated items
    rows_q = (
        base
        .add_columns(member_count.label("member_count"))
        .order_by(Project.created_at.desc())
        .offset(offset)
        .limit(limit)
    )

    if user is not None:
        is_member = (
            exists()
            .where(
                ProjectMembership.project_id == Project.id,
                ProjectMembership.user_id == user.id,
            )
            .correlate(Project)
            .label("is_member")
        )
        has_pending = (
            exists()
            .where(
                JoinRequest.project_id == Project.id,
                JoinRequest.user_id == user.id,
                JoinRequest.status == "pending",
            )
            .correlate(Project)
            .label("has_pending_request")
        )
        rows_q = rows_q.add_columns(is_member, has_pending)

    result = await db.execute(rows_q)
    rows = result.all()

    items: list[dict] = []
    for row in rows:
        if user is not None:
            proj, mc, is_m, has_p = row
        else:
            proj, mc = row

        item = {
            "slug": proj.slug,
            "name": proj.name,
            "description": proj.description,
            "stack": proj.stack,
            "member_count": mc,
            "created_at": proj.created_at.isoformat(),
        }
        if user is not None:
            item["is_member"] = bool(is_m)
            item["has_pending_request"] = bool(has_p)
        items.append(item)

    return {
        "items": items,
        "total": total,
        "offset": offset,
        "limit": limit,
    }


# ---------------------------------------------------------------------------
# 2. POST /api/projects/{slug}/join  -  request to join
# ---------------------------------------------------------------------------

@router.post("/api/projects/{slug}/join", status_code=201)
async def request_join(
    slug: str,
    request: Request,
    body: JoinRequestCreate | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = await _get_public_project(db, slug)

    is_htmx = request.headers.get("HX-Request") == "true"

    # Already a member?
    is_member = await db.execute(
        select(ProjectMembership).where(
            ProjectMembership.project_id == project.id,
            ProjectMembership.user_id == user.id,
        )
    )
    if is_member.scalar_one_or_none() is not None:
        if is_htmx:
            from dashboard.i18n import t
            lang = request.cookies.get("ai_workflow_lang", "uk")
            html = f'<div class="join-action"><span class="badge-member">{html_escape(t("catalog.is_member", lang))}</span></div>'
            return HTMLResponse(html, status_code=200)
        raise HTTPException(status_code=409, detail="Already a member")

    # Pending request?
    pending = await db.execute(
        select(JoinRequest).where(
            JoinRequest.project_id == project.id,
            JoinRequest.user_id == user.id,
            JoinRequest.status == "pending",
        )
    )
    if pending.scalar_one_or_none() is not None:
        if is_htmx:
            from dashboard.i18n import t
            lang = request.cookies.get("ai_workflow_lang", "uk")
            html = f'<div class="join-action"><button class="btn-join-sent" disabled>{html_escape(t("catalog.request_sent", lang))}</button></div>'
            return HTMLResponse(html, status_code=200)
        raise HTTPException(status_code=409, detail="Request already pending")

    jr = JoinRequest(
        user_id=user.id,
        project_id=project.id,
        status="pending",
        message=body.message if body else None,
    )
    db.add(jr)
    await db.flush()

    # Notify all project owners about the new join request
    from dashboard.routers.notifications import create_notification
    from dashboard.i18n import t as i18n_t
    owners = (await db.execute(
        select(ProjectMembership, User)
        .join(User, ProjectMembership.user_id == User.id)
        .where(
            ProjectMembership.project_id == project.id,
            ProjectMembership.role == "owner",
        )
    )).all()
    for _membership, owner_user in owners:
        owner_lang = owner_user.lang or "uk"
        await create_notification(
            db,
            user_id=owner_user.id,
            type="join_request_new",
            title=i18n_t("notifications.new_join_request", owner_lang,
                         user=user.display_name or user.email,
                         project=project.name),
            body=jr.message or "",
            link=f"/#join-requests",
            ref_id=jr.id,
        )

    await db.commit()
    await db.refresh(jr)

    # HTMX response: return updated join-action HTML
    if request.headers.get("HX-Request") == "true":
        from dashboard.i18n import t
        lang = request.cookies.get("ai_workflow_lang", "uk")
        label = html_escape(t("catalog.request_sent", lang))
        html = f'<div class="join-action"><button class="btn-join-sent" disabled>{label}</button></div>'
        return HTMLResponse(html, status_code=201)

    return {
        "id": str(jr.id),
        "status": jr.status,
        "created_at": jr.created_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# 3. PATCH /api/projects/{slug}/join-requests/{request_id}
# ---------------------------------------------------------------------------

@router.patch("/api/projects/{slug}/join-requests/{request_id}")
async def review_join_request(
    slug: str,
    request_id: str,
    request: Request,
    body: JoinRequestAction | None = None,
    action: Literal["approve", "reject"] | None = Query(None),
    role: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Accept action from JSON body (API clients) or query param (HTMX hx-vals)
    resolved_action = (body.action if body else None) or action
    if resolved_action is None:
        raise HTTPException(status_code=422, detail="action is required ('approve' or 'reject')")

    # Validate optional role for approve
    assign_role = role or "viewer"
    if assign_role not in ("viewer", "developer", "editor"):
        raise HTTPException(status_code=422, detail="role must be one of: viewer, developer, editor")

    rid = _parse_uuid(request_id)
    # Use visibility-agnostic lookup so owners can manage requests even if
    # the project was switched to private after requests were submitted.
    project = await _get_project_by_slug(db, slug)
    await _require_owner_or_superadmin(db, user, project)

    now = datetime.now(timezone.utc)

    # Optimistic lock: only update if still pending
    new_status = "approved" if resolved_action == "approve" else "rejected"
    stmt = (
        update(JoinRequest)
        .where(
            JoinRequest.id == rid,
            JoinRequest.project_id == project.id,
            JoinRequest.status == "pending",
        )
        .values(
            status=new_status,
            reviewed_at=now,
            reviewed_by=user.id,
        )
        .execution_options(synchronize_session=False)
    )
    result = await db.execute(stmt)

    if result.rowcount == 0:  # type: ignore[union-attr]
        # Either request doesn't exist for this project, or already processed
        raise HTTPException(status_code=409, detail="Request already processed")

    # Fetch the JoinRequest for both branches (approve needs user_id, both need notification)
    jr_result = await db.execute(
        select(JoinRequest).where(JoinRequest.id == rid)
    )
    jr = jr_result.scalar_one()

    # On approve: add membership with ON CONFLICT DO NOTHING
    if resolved_action == "approve":
        ins = (
            insert(ProjectMembership)
            .values(
                id=uuid.uuid4(),
                user_id=jr.user_id,
                project_id=project.id,
                role=assign_role,
            )
            .on_conflict_do_nothing(
                constraint="uq_membership_user_project",
            )
        )
        await db.execute(ins)

    # US-8: Notify the requester about approve/reject
    from dashboard.routers.notifications import create_notification
    from dashboard.i18n import t as i18n_t
    requester_result = await db.execute(select(User).where(User.id == jr.user_id))
    requester = requester_result.scalar_one()
    requester_lang = requester.lang or "uk"

    if resolved_action == "approve":
        await create_notification(
            db,
            user_id=jr.user_id,
            type="join_request_approved",
            title=i18n_t("notifications.join_request_approved", requester_lang, project=project.name),
            link="/#board",
            ref_id=jr.id,
        )
    else:
        await create_notification(
            db,
            user_id=jr.user_id,
            type="join_request_rejected",
            title=i18n_t("notifications.join_request_rejected", requester_lang, project=project.name),
            link="/catalog",
            ref_id=jr.id,
        )

    await db.commit()

    # HTMX response: return updated row HTML
    if request.headers.get("HX-Request") == "true":
        from dashboard.i18n import t
        lang = request.cookies.get("ai_workflow_lang", "uk")

        # Reload the JoinRequest + user for the response
        jr_fresh = await db.execute(
            select(JoinRequest).where(JoinRequest.id == rid)
        )
        jr_obj = jr_fresh.scalar_one()
        user_result = await db.execute(select(User).where(User.id == jr_obj.user_id))
        jr_user = user_result.scalar_one()

        # Escape all user-controlled data to prevent XSS
        safe_name = html_escape(jr_user.display_name or "")
        safe_email = html_escape(jr_user.email or "")
        display = safe_name or safe_email
        initial = html_escape(
            (jr_user.display_name[:1].upper() if jr_user.display_name else jr_user.email[:1].upper())
        )
        date_str = jr_obj.created_at.strftime("%d.%m.%Y %H:%M")

        badge_class = "badge-approved" if resolved_action == "approve" else "badge-rejected"
        badge_key = "join_requests.approved" if resolved_action == "approve" else "join_requests.rejected"
        badge_text = html_escape(t(badge_key, lang))

        html = f'''<div class="join-request-row processed" id="jr-{rid}">
  <div class="join-request-avatar">{initial}</div>
  <div class="join-request-info">
    <div class="join-request-name">{display}</div>
    <div class="join-request-email">{safe_email}</div>
    <div class="join-request-date">{date_str}</div>
  </div>
  <div class="join-request-actions">
    <span class="{badge_class}">{badge_text}</span>
  </div>
</div>'''
        return HTMLResponse(html, headers={"HX-Trigger": "refreshMembersList"})

    return {
        "id": str(rid),
        "status": new_status,
        "reviewed_at": now.isoformat(),
    }


# ---------------------------------------------------------------------------
# 4. GET /api/projects/{slug}/join-requests
# ---------------------------------------------------------------------------

_VALID_STATUSES = {"pending", "approved", "rejected", "cancelled", "all"}


@router.get("/api/projects/{slug}/join-requests")
async def list_project_join_requests(
    slug: str,
    status: str = "pending",
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status filter. Must be one of: {', '.join(sorted(_VALID_STATUSES))}",
        )

    # Use visibility-agnostic lookup so owners can view requests even if
    # the project was switched to private after requests were submitted.
    project = await _get_project_by_slug(db, slug)
    await _require_owner_or_superadmin(db, user, project)

    base = (
        select(JoinRequest, User)
        .join(User, JoinRequest.user_id == User.id)
        .where(JoinRequest.project_id == project.id)
    )
    if status != "all":
        base = base.where(JoinRequest.status == status)

    # Total count
    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar_one()

    # Paginated
    rows_q = (
        base
        .order_by(JoinRequest.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = (await db.execute(rows_q)).all()

    items = []
    for jr, u in rows:
        items.append({
            "id": str(jr.id),
            "user": {
                "id": str(u.id),
                "email": u.email,
                "display_name": u.display_name,
            },
            "status": jr.status,
            "message": jr.message,
            "created_at": jr.created_at.isoformat(),
        })

    return {
        "items": items,
        "total": total,
        "offset": offset,
        "limit": limit,
    }


# ---------------------------------------------------------------------------
# 5. GET /api/admin/join-requests  -  superadmin view across all projects
# ---------------------------------------------------------------------------

@router.get("/api/admin/join-requests")
async def list_all_join_requests(
    status: str = "pending",
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not user.is_superadmin:
        raise HTTPException(status_code=403, detail="Forbidden")

    if status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status filter. Must be one of: {', '.join(sorted(_VALID_STATUSES))}",
        )

    base = (
        select(JoinRequest, User, Project)
        .join(User, JoinRequest.user_id == User.id)
        .join(Project, JoinRequest.project_id == Project.id)
    )
    if status != "all":
        base = base.where(JoinRequest.status == status)

    # Total count
    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar_one()

    # Paginated
    rows_q = (
        base
        .order_by(JoinRequest.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = (await db.execute(rows_q)).all()

    items = []
    for jr, u, proj in rows:
        items.append({
            "id": str(jr.id),
            "project": {
                "slug": proj.slug,
                "name": proj.name,
            },
            "user": {
                "id": str(u.id),
                "email": u.email,
                "display_name": u.display_name,
            },
            "status": jr.status,
            "message": jr.message,
            "created_at": jr.created_at.isoformat(),
        })

    return {
        "items": items,
        "total": total,
        "offset": offset,
        "limit": limit,
    }


# ---------------------------------------------------------------------------
# 6. GET /api/my/join-requests  -  current user's own requests (US-9)
# ---------------------------------------------------------------------------

@router.get("/api/my/join-requests")
async def list_my_join_requests(
    status: str = "all",
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if status not in _VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid status filter. Must be one of: {', '.join(sorted(_VALID_STATUSES))}",
        )

    base = (
        select(JoinRequest, Project)
        .join(Project, JoinRequest.project_id == Project.id)
        .where(JoinRequest.user_id == user.id)
    )
    if status != "all":
        base = base.where(JoinRequest.status == status)

    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar_one()

    rows_q = (
        base
        .order_by(JoinRequest.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = (await db.execute(rows_q)).all()

    items = []
    for jr, proj in rows:
        items.append({
            "id": str(jr.id),
            "project": {
                "slug": proj.slug,
                "name": proj.name,
            },
            "status": jr.status,
            "message": jr.message,
            "created_at": jr.created_at.isoformat(),
            "reviewed_at": jr.reviewed_at.isoformat() if jr.reviewed_at else None,
        })

    return {
        "items": items,
        "total": total,
        "offset": offset,
        "limit": limit,
    }


# ---------------------------------------------------------------------------
# 7. PATCH /api/my/join-requests/{id}/cancel  -  cancel own request (US-10)
# ---------------------------------------------------------------------------

@router.patch("/api/my/join-requests/{request_id}/cancel")
async def cancel_my_join_request(
    request_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rid = _parse_uuid(request_id)

    # Verify the request belongs to the current user
    jr_result = await db.execute(
        select(JoinRequest).where(JoinRequest.id == rid)
    )
    jr = jr_result.scalar_one_or_none()
    if jr is None:
        raise HTTPException(status_code=404, detail="Not found")
    if jr.user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")
    if jr.status != "pending":
        raise HTTPException(status_code=409, detail="Request is not pending")

    # Optimistic lock: only update if still pending
    now = datetime.now(timezone.utc)
    stmt = (
        update(JoinRequest)
        .where(
            JoinRequest.id == rid,
            JoinRequest.status == "pending",
        )
        .values(
            status="cancelled",
            reviewed_at=now,
            reviewed_by=user.id,
        )
        .execution_options(synchronize_session=False)
    )
    result = await db.execute(stmt)
    if result.rowcount == 0:  # type: ignore[union-attr]
        raise HTTPException(status_code=409, detail="Request already processed")

    await db.commit()

    # HTMX response: return updated card HTML
    if request.headers.get("HX-Request") == "true":
        from dashboard.i18n import t
        lang = request.cookies.get("ai_workflow_lang", "uk")

        # Reload JoinRequest + project for the response
        jr_fresh = await db.execute(
            select(JoinRequest, Project)
            .join(Project, JoinRequest.project_id == Project.id)
            .where(JoinRequest.id == rid)
        )
        jr_obj, proj = jr_fresh.one()

        safe_project = html_escape(proj.name)
        date_str = jr_obj.created_at.strftime("%d.%m.%Y %H:%M")
        badge_text = html_escape(t("join_requests.cancelled", lang))

        html = f'''<div class="my-request-card" id="my-jr-{rid}">
  <div class="my-request-info">
    <div class="my-request-project">{safe_project}</div>
    <div class="my-request-date">{date_str}</div>
  </div>
  <div class="my-request-actions">
    <span class="badge-cancelled">{badge_text}</span>
  </div>
</div>'''
        return HTMLResponse(html)


# ---------------------------------------------------------------------------
# 10. GET /api/users/search  -  search users (for invite)
# ---------------------------------------------------------------------------

@router.get("/api/users/search")
async def search_users(
    request: Request,
    q: str = Query("", min_length=1, max_length=100),
    project: str = Query(""),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Search users by email or display_name. Excludes current project members."""
    escaped = _escape_like(q.strip())
    if not escaped:
        return []

    query = (
        select(User)
        .where(
            User.is_blocked == False,  # noqa: E712
            or_(
                User.email.ilike(f"%{escaped}%"),
                User.display_name.ilike(f"%{escaped}%"),
            ),
        )
        .limit(10)
    )

    # Exclude users who are already members of the project
    if project:
        proj = (await db.execute(select(Project).where(Project.slug == project))).scalar_one_or_none()
        if proj:
            member_ids = select(ProjectMembership.user_id).where(
                ProjectMembership.project_id == proj.id
            )
            query = query.where(User.id.notin_(member_ids))

    rows = (await db.execute(query)).scalars().all()
    return [
        {
            "id": str(u.id),
            "email": u.email,
            "display_name": u.display_name or "",
        }
        for u in rows
    ]


# ---------------------------------------------------------------------------
# 11. POST /api/projects/{slug}/invite  -  invite user directly
# ---------------------------------------------------------------------------

class InviteRequest(BaseModel):
    user_id: str
    role: Literal["viewer", "developer", "editor"] = "viewer"


@router.post("/api/projects/{slug}/invite", status_code=201)
async def invite_user(
    slug: str,
    request: Request,
    body: InviteRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Owner invites a user directly to the project (no join request needed)."""
    project = await _get_project_by_slug(db, slug)
    await _require_owner_or_superadmin(db, user, project)

    target_uid = _parse_uuid(body.user_id)

    # Check target user exists
    target_user = (await db.execute(select(User).where(User.id == target_uid))).scalar_one_or_none()
    if target_user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Already a member?
    existing = (await db.execute(
        select(ProjectMembership).where(
            ProjectMembership.project_id == project.id,
            ProjectMembership.user_id == target_uid,
        )
    )).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Already a member")

    membership = ProjectMembership(
        user_id=target_uid,
        project_id=project.id,
        role=body.role,
    )
    db.add(membership)

    # Cancel any pending join request from this user
    await db.execute(
        update(JoinRequest)
        .where(
            JoinRequest.project_id == project.id,
            JoinRequest.user_id == target_uid,
            JoinRequest.status == "pending",
        )
        .values(status="approved", reviewed_at=datetime.now(timezone.utc), reviewed_by=user.id)
    )

    # Notify the invited user
    from dashboard.routers.notifications import create_notification
    from dashboard.i18n import t as i18n_t
    target_lang = target_user.lang or "uk"
    await create_notification(
        db,
        user_id=target_uid,
        type="invited_to_project",
        title=i18n_t("notifications.invited_to_project", target_lang, project=project.name),
        link=f"/#members",
        ref_id=project.id,
    )

    await db.commit()
    await db.refresh(membership)

    if request.headers.get("HX-Request") == "true":
        return await _member_row_html(request, db, membership, project.slug)

    return {
        "id": str(membership.id),
        "user_id": str(target_uid),
        "role": membership.role,
    }

    return {
        "id": str(rid),
        "status": "cancelled",
    }


# ---------------------------------------------------------------------------
# 8. PATCH /api/projects/{slug}/members/{membership_id}  -  change role
# ---------------------------------------------------------------------------

class MemberRoleUpdate(BaseModel):
    role: Literal["viewer", "developer", "editor"]


@router.patch("/api/projects/{slug}/members/{membership_id}")
async def change_member_role(
    slug: str,
    membership_id: str,
    request: Request,
    body: MemberRoleUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):

    mid = _parse_uuid(membership_id)
    project = await _get_project_by_slug(db, slug)
    await _require_owner_or_superadmin(db, user, project)

    # Load membership
    m_result = await db.execute(
        select(ProjectMembership).where(
            ProjectMembership.id == mid,
            ProjectMembership.project_id == project.id,
        )
    )
    membership = m_result.scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=404, detail="Membership not found")

    # Cannot change owner role
    if membership.role == "owner":
        raise HTTPException(status_code=403, detail="Cannot change owner role")

    # No-op if same role
    if membership.role == body.role:
        # Still return the row HTML for HTMX
        if request.headers.get("HX-Request") == "true":
            return await _member_row_html(request, db, membership, project.slug)
        return {"id": str(mid), "role": membership.role}

    old_role = membership.role
    membership.role = body.role

    # Notify the member about role change (in their language)
    from dashboard.routers.notifications import create_notification
    from dashboard.i18n import t as i18n_t
    member_user = (await db.execute(select(User).where(User.id == membership.user_id))).scalar_one()
    member_lang = member_user.lang or "uk"
    await create_notification(
        db,
        user_id=membership.user_id,
        type="role_changed",
        title=i18n_t("notifications.role_changed", member_lang, project=project.name, role=body.role),
        link="/#members",
        ref_id=membership.id,
    )

    await db.commit()
    await db.refresh(membership)

    if request.headers.get("HX-Request") == "true":
        return await _member_row_html(request, db, membership, project.slug)

    return {"id": str(mid), "role": membership.role}


# ---------------------------------------------------------------------------
# 9. DELETE /api/projects/{slug}/members/{membership_id}  -  remove member
# ---------------------------------------------------------------------------

@router.delete("/api/projects/{slug}/members/{membership_id}")
async def remove_member(
    slug: str,
    membership_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    mid = _parse_uuid(membership_id)
    project = await _get_project_by_slug(db, slug)
    await _require_owner_or_superadmin(db, user, project)

    # Load membership
    m_result = await db.execute(
        select(ProjectMembership).where(
            ProjectMembership.id == mid,
            ProjectMembership.project_id == project.id,
        )
    )
    membership = m_result.scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=404, detail="Membership not found")

    # Cannot remove owner
    if membership.role == "owner":
        raise HTTPException(status_code=403, detail="Cannot remove project owner")

    removed_user_id = membership.user_id

    # Notify the removed user (in their language)
    from dashboard.routers.notifications import create_notification
    from dashboard.i18n import t as i18n_t
    member_user = (await db.execute(select(User).where(User.id == removed_user_id))).scalar_one()
    member_lang = member_user.lang or "uk"
    await create_notification(
        db,
        user_id=removed_user_id,
        type="removed_from_project",
        title=i18n_t("notifications.removed_from_project", member_lang, project=project.name),
        link="/catalog",
        ref_id=project.id,
    )

    await db.delete(membership)
    await db.commit()

    if request.headers.get("HX-Request") == "true":
        return HTMLResponse("", status_code=200)

    return {"status": "removed"}


# ---------------------------------------------------------------------------
# Helper: render a single member row as HTML (for HTMX swap)
# ---------------------------------------------------------------------------

async def _member_row_html(
    request: Request,
    db: AsyncSession,
    membership: ProjectMembership,
    project_slug: str,
) -> HTMLResponse:
    """Render a single member-row HTML fragment for HTMX outerHTML swap."""
    from dashboard.i18n import t

    lang = request.cookies.get("ai_workflow_lang", "uk")
    member_user = (await db.execute(select(User).where(User.id == membership.user_id))).scalar_one()

    safe_name = html_escape(member_user.display_name or "")
    safe_email = html_escape(member_user.email or "")
    display = safe_name or safe_email
    # JS-safe string for use in Alpine.js event handler attributes
    display_js = html_escape(_js_string(member_user.display_name or member_user.email or ""))
    initial = html_escape(
        (member_user.display_name[:1].upper() if member_user.display_name else member_user.email[:1].upper())
    )
    date_str = membership.created_at.strftime("%d.%m.%Y")
    joined_label = html_escape(t("members.joined", lang))
    remove_label = html_escape(t("members.remove", lang))

    role = membership.role
    role_label_viewer = html_escape(t("role.viewer", lang))
    role_label_developer = html_escape(t("role.developer", lang))
    role_label_editor = html_escape(t("role.editor", lang))

    viewer_sel = ' selected' if role == 'viewer' else ''
    developer_sel = ' selected' if role == 'developer' else ''
    editor_sel = ' selected' if role == 'editor' else ''

    mid = membership.id

    html = f'''<div class="member-row" id="member-{mid}">
  <div class="member-avatar">{initial}</div>
  <div class="member-info">
    <div class="member-name">{display}</div>
    <div class="member-email">{safe_email}</div>
    <div class="member-date">{joined_label}: {date_str}</div>
  </div>
  <div class="member-actions">
    <select class="role-select"
            data-member-id="{mid}"
            data-member-name="{display}"
            data-current-role="{role}"
            @change="handleRoleChange($event, '{mid}', {display_js}, '{role}')">
      <option value="viewer"{viewer_sel}>{role_label_viewer}</option>
      <option value="developer"{developer_sel}>{role_label_developer}</option>
      <option value="editor"{editor_sel}>{role_label_editor}</option>
    </select>
    <button class="btn-delete-member"
            @click="openDeleteModal('{mid}', {display_js})"
            title="{remove_label}">&#10005;</button>
  </div>
</div>'''
    return HTMLResponse(html)
