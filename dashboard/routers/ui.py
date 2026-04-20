"""UI router: serves Jinja2-rendered pages and HTMX partial fragments."""
import json
from pathlib import Path

from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, func, exists
from sqlalchemy.ext.asyncio import AsyncSession

from dashboard.auth.middleware import get_current_user, get_optional_user
from dashboard.db.engine import get_db
from dashboard.db.models.user import User
from dashboard.db.models.project import Project, ProjectMembership
from dashboard.db.models.join_request import JoinRequest
from dashboard.i18n import DEFAULT_LANG
from dashboard.template_setup import templates

router = APIRouter()


def _lang(request: Request, user: User | None = None) -> str:
    """Resolve language: query param > cookie (explicit switch) > user pref > default."""
    if q := request.query_params.get("lang"):
        return q
    if cookie := request.cookies.get("ai_workflow_lang"):
        return cookie
    if user and hasattr(user, "lang") and user.lang:
        return user.lang
    return DEFAULT_LANG


def _ctx(request: Request, user: User, **extra) -> dict:
    """Build common template context."""
    lang = _lang(request, user)
    return {
        "request": request,
        "user": user,
        "lang": lang,
        "is_superadmin": user.is_superadmin,
        "user_role": extra.pop("user_role", ""),
        **extra,
    }


async def _get_user_role(db: AsyncSession, user: User, project_slug: str) -> str:
    """Return user's effective role for project, or '' if no access."""
    if not project_slug:
        return ""
    proj = (await db.execute(select(Project).where(Project.slug == project_slug))).scalar_one_or_none()
    if not proj:
        return ""
    from dashboard.auth.permissions import check_project_access
    role = await check_project_access(db, user, proj, "viewer")
    return role or ""


# ── Main pages ──────────────────────────────────────────────────────

_setup_completed_cache = False

@router.get("/")
async def dashboard_page(request: Request, user: User | None = Depends(get_optional_user)):
    global _setup_completed_cache
    from dashboard.auth.jwt import SETUP_MODE
    if SETUP_MODE:
        return RedirectResponse("/setup.html")

    # Cache setup_completed check — avoids DB round-trip on every page load
    if not _setup_completed_cache:
        try:
            from dashboard.db.engine import async_session
            from dashboard.db.models.system_config import SystemConfig
            async with async_session() as db:
                result = await db.execute(
                    select(SystemConfig).where(SystemConfig.key == "setup_completed")
                )
                cfg = result.scalar_one_or_none()
                if cfg and cfg.value == "true":
                    _setup_completed_cache = True
                else:
                    return RedirectResponse("/setup.html")
        except Exception:
            pass

    if not user:
        return RedirectResponse("/login.html")

    ctx = _ctx(request, user)
    return templates.TemplateResponse("dashboard.html", ctx)


# ── Static pages (login, setup, admin) ──────────────────────────────

@router.get("/setup.html")
def serve_setup():
    from pathlib import Path
    html = (Path(__file__).parent.parent / "setup.html").read_text(encoding="utf-8")
    return HTMLResponse(html, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


@router.get("/login.html")
def serve_login():
    from pathlib import Path
    p = Path(__file__).parent.parent / "login.html"
    if not p.exists():
        return HTMLResponse("<h1>login.html not yet created</h1>")
    html = p.read_text(encoding="utf-8")
    return HTMLResponse(html, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


@router.get("/admin.html")
def serve_admin():
    from pathlib import Path
    html = (Path(__file__).parent.parent / "admin.html").read_text(encoding="utf-8")
    return HTMLResponse(html, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


# ── Public Catalog (standalone page, no auth required) ───────────

def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

@router.get("/catalog")
async def catalog_page(
    request: Request,
    q: str = "",
    offset: int = 0,
    limit: int = 20,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Public projects catalog — SSR with HTMX progressive enhancement."""
    from sqlalchemy import or_

    lang = _lang(request, user)

    # Clamp params
    offset = max(offset, 0)
    limit = max(1, min(limit, 50))

    # Base query
    base = select(Project).where(Project.visibility == "public")

    if q.strip():
        pattern = f"%{_escape_like(q.strip())}%"
        base = base.where(or_(
            Project.name.ilike(pattern),
            Project.description.ilike(pattern),
            Project.stack.ilike(pattern),
        ))

    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()

    member_count_sq = (
        select(func.count(ProjectMembership.id))
        .where(ProjectMembership.project_id == Project.id)
        .correlate(Project)
        .scalar_subquery()
    )

    rows_q = (
        base
        .add_columns(member_count_sq.label("member_count"))
        .order_by(Project.created_at.desc())
        .offset(offset)
        .limit(limit)
    )

    # Use correlated EXISTS subqueries for membership/pending (same approach as API)
    if user:
        is_member_sq = (
            exists()
            .where(
                ProjectMembership.project_id == Project.id,
                ProjectMembership.user_id == user.id,
            )
            .correlate(Project)
            .label("is_member")
        )
        has_pending_sq = (
            exists()
            .where(
                JoinRequest.project_id == Project.id,
                JoinRequest.user_id == user.id,
                JoinRequest.status == "pending",
            )
            .correlate(Project)
            .label("has_pending")
        )
        rows_q = rows_q.add_columns(is_member_sq, has_pending_sq)

    result = await db.execute(rows_q)
    projects = []
    for row in result.all():
        if user:
            proj, mc, is_m, has_p = row
        else:
            proj, mc = row
            is_m, has_p = False, False
        projects.append({
            "slug": proj.slug,
            "name": proj.name,
            "description": proj.description or "",
            "stack": proj.stack or "",
            "member_count": mc,
            "created_at": proj.created_at,
            "is_member": bool(is_m),
            "has_pending": bool(has_p),
        })

    ctx = {
        "request": request,
        "user": user,
        "lang": lang,
        "projects": projects,
        "q": q,
        "total": total,
        "offset": offset,
        "limit": limit,
        "flash_message": request.cookies.get("flash_message"),
        "flash_error": request.cookies.get("flash_error"),
    }

    # HTMX partial: return only the results fragment
    if request.headers.get("HX-Request") == "true":
        return templates.TemplateResponse("partials/_catalog_results.html", ctx)

    return templates.TemplateResponse("catalog.html", ctx)


@router.post("/catalog/join/{slug}")
async def catalog_join_fallback(
    slug: str,
    request: Request,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """No-JS fallback: process join request via form POST, redirect back to catalog."""
    if not user:
        return RedirectResponse("/login.html?next=/catalog", status_code=303)

    try:
        # Reuse the logic from the API router
        from dashboard.routers.catalog import _get_public_project
        project = await _get_public_project(db, slug)

        # Check membership
        is_member = await db.execute(
            select(ProjectMembership).where(
                ProjectMembership.project_id == project.id,
                ProjectMembership.user_id == user.id,
            )
        )
        if is_member.scalar_one_or_none():
            resp = RedirectResponse("/catalog", status_code=303)
            return resp

        # Check pending
        pending = await db.execute(
            select(JoinRequest).where(
                JoinRequest.project_id == project.id,
                JoinRequest.user_id == user.id,
                JoinRequest.status == "pending",
            )
        )
        if pending.scalar_one_or_none():
            resp = RedirectResponse("/catalog", status_code=303)
            return resp

        jr = JoinRequest(
            user_id=user.id,
            project_id=project.id,
            status="pending",
        )
        db.add(jr)
        await db.commit()

        from dashboard.i18n import t
        lang = _lang(request, user)
        resp = RedirectResponse("/catalog", status_code=303)
        resp.set_cookie("flash_message", t("catalog.request_sent", lang), max_age=5)
        return resp

    except Exception:
        from dashboard.i18n import t
        lang = _lang(request, user)
        resp = RedirectResponse("/catalog", status_code=303)
        resp.set_cookie("flash_error", t("catalog.error_generic", lang), max_age=5)
        return resp


# ── Artifacts page (standalone, opens in new window) ─────────────

@router.get("/artifacts/{project}/{task_id}")
async def artifacts_page(
    project: str,
    task_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Full-page artifact viewer for a single task."""
    from dashboard.routers.projects import _check_project_access
    from dashboard.db.models.artifact import Artifact
    from dashboard.db.models.backlog import BacklogItem
    from dashboard.db.models.project import Project

    await _check_project_access(project, user, db, "viewer")

    artifacts = []
    task_title = f"Task {task_id}"

    proj = (await db.execute(select(Project).where(Project.slug == project))).scalar_one_or_none()
    if proj:
        bi = (await db.execute(
            select(BacklogItem).where(
                BacklogItem.project_id == proj.id,
                BacklogItem.sequence_number == int(task_id),
            )
        )).scalar_one_or_none()

        if bi:
            task_title = bi.title
            result = await db.execute(
                select(
                    Artifact.id, Artifact.stage, Artifact.name,
                    Artifact.artifact_type, Artifact.mime_type,
                    Artifact.size_bytes,
                ).where(
                    Artifact.backlog_item_id == bi.id,
                ).order_by(Artifact.stage, Artifact.created_at)
            )
            for row in result.all():
                a_id, stage, name, a_type, mime, size = row
                artifacts.append({
                    "id": str(a_id),
                    "stage": stage or "",
                    "name": name,
                    "artifact_type": a_type,
                    "mime_type": mime or "",
                    "size_bytes": size,
                })

    lang = _lang(request, user)
    return templates.TemplateResponse("artifacts_page.html", {
        "request": request,
        "user": user,
        "lang": lang,
        "project": project,
        "task_id": task_id,
        "task_title": task_title,
        "artifacts": artifacts,
    })


# ── Bootstrap API (single request replaces 6 sequential calls) ────

@router.get("/api/bootstrap")
async def bootstrap(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all data needed for dashboard init in one response.
    Replaces sequential calls to /auth/me + /projects + /pipeline-config."""
    from sqlalchemy import or_, case, literal_column
    from sqlalchemy.sql import func as sqlfunc
    from dashboard.db.models.project import Project, ProjectMembership

    # Single query: membership projects + public projects, with effective role + base_branch
    result = await db.execute(
        select(
            Project.id,
            Project.slug,
            sqlfunc.coalesce(ProjectMembership.role, literal_column("'viewer'")).label("effective_role"),
            Project.base_branch,
        )
        .outerjoin(
            ProjectMembership,
            (ProjectMembership.project_id == Project.id)
            & (ProjectMembership.user_id == user.id),
        )
        .where(
            or_(
                ProjectMembership.id.isnot(None),
                Project.visibility == "public",
            )
        )
        .distinct()
        .order_by(Project.slug)
    )
    rows = result.all()

    # Per-instance bindings: map slug → local_path. A project is visible in
    # the dropdown regardless of binding state, but if the slug is missing
    # from this map (or maps to None) the dashboard knows the user must
    # set up a local copy before the normal tabs work.
    from dashboard.services.instance_paths import (
        get_current_instance_id, get_all_bindings_for_instance,
    )
    instance_id = get_current_instance_id()
    bindings_by_pid: dict = {}
    if instance_id is not None:
        bindings_by_pid = await get_all_bindings_for_instance(db)

    projects = [row[1] for row in rows]
    roles = {row[1]: row[2] for row in rows}
    base_branches = {row[1]: row[3] for row in rows}
    bindings = {row[1]: bindings_by_pid.get(row[0]) for row in rows}

    return {
        "user": {
            "id": str(user.id),
            "email": user.email,
            "display_name": user.display_name,
            "lang": user.lang,
            "is_superadmin": user.is_superadmin,
        },
        "projects": projects,
        "roles": roles,
        "base_branches": base_branches,
        "bindings": bindings,
    }


# ── HTMX: setup-binding partial (shown when project has no local copy) ───

@router.get("/ui/partials/setup-binding")
async def setup_binding_partial(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    project: str = Query("", alias="project"),
):
    """Render the 'set up local copy' form for an unbound project on this instance.

    Auth: caller must have ≥ developer access on the project (binding writes
    to disk and creates files). Viewers don't see this — they get the
    DB-only tabs that work without a binding.
    """
    from dashboard.routers.projects import _check_project_access
    await _check_project_access(project, user, db, "developer")
    ctx = _ctx(request, user, project=project, user_role=await _get_user_role(db, user, project))
    return templates.TemplateResponse(request, "partials/_setup_binding.html", ctx)


# ── HTMX Sync Check ───────────────────────────────────────────────

@router.get("/ui/partials/sync-check")
async def sync_check(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    project: str = Query("", alias="project"),
):
    """Return empty if no updates, or banner HTML if updates available."""
    if project:
        from dashboard.routers.projects import _check_project_access
        try:
            await _check_project_access(project, user, db, "viewer")
        except Exception:
            return HTMLResponse("")
    return HTMLResponse("")


# ── HTMX Actions (return refreshed tab partials) ──────────────────

@router.post("/ui/actions/move-to-todo")
async def action_move_to_todo(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    project: str = Query("", alias="project"),
    item_id: str = Query("", alias="item_id"),
):
    """Move a backlog item to 'todo' status, return refreshed backlog tab."""
    from dashboard.routers.projects import _check_project_access
    from dashboard.db.models.backlog import BacklogItem
    from dashboard.db.models.project import Project

    await _check_project_access(project, user, db, "editor")
    proj = (await db.execute(select(Project).where(Project.slug == project))).scalar_one_or_none()
    if proj:
        bi = (await db.execute(
            select(BacklogItem).where(BacklogItem.project_id == proj.id, BacklogItem.sequence_number == int(item_id))
        )).scalar_one_or_none()
        if bi:
            bi.status = "todo"
            await db.commit()

    user_role = await _get_user_role(db, user, project) if project else ""
    ctx = _ctx(request, user, project=project, tab_name="backlog", user_role=user_role)
    ctx["backlog_items"] = await _load_backlog(project, db)
    ctx["artifact_counts"] = await _load_artifact_counts(project, db)
    return templates.TemplateResponse("partials/tabs/_backlog.html", ctx)


@router.post("/ui/actions/archive-done")
async def action_archive_done(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    project: str = Query("", alias="project"),
):
    """Archive all 'done' items, return refreshed board tab."""
    from dashboard.routers.projects import _check_project_access
    from dashboard.db.models.backlog import BacklogItem
    from dashboard.db.models.project import Project

    await _check_project_access(project, user, db, "editor")
    proj = (await db.execute(select(Project).where(Project.slug == project))).scalar_one_or_none()
    if proj:
        result = await db.execute(
            select(BacklogItem).where(BacklogItem.project_id == proj.id, BacklogItem.status == "done")
        )
        for bi in result.scalars().all():
            bi.status = "archived"
        await db.commit()

    user_role = await _get_user_role(db, user, project) if project else ""
    ctx = _ctx(request, user, project=project, tab_name="board", user_role=user_role)
    ctx["backlog_items"] = await _load_backlog(project, db)
    ctx["artifact_counts"] = await _load_artifact_counts(project, db)
    return templates.TemplateResponse("partials/tabs/_board.html", ctx)


# ── HTMX Tab Partials ──────────────────────────────────────────────

@router.get("/ui/partials/tabs/{tab_name}")
async def tab_partial(
    tab_name: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    project: str = Query("", alias="project"),
    q: str = Query("", alias="q"),
):
    """Serve a single tab as an HTML fragment for HTMX swap."""
    allowed_tabs = {
        "backlog", "board", "archive", "pipeline", "agents",
        "terminal", "transcriber", "logs",
        "newproject", "profile", "join-requests", "my-requests",
        "members",
    }
    if tab_name not in allowed_tabs:
        return HTMLResponse("<p>Tab not found</p>", status_code=404)

    # Access check + role resolution in a single pass (avoids duplicate Project+Membership queries)
    from dashboard.auth.permissions import ROLE_RANK
    user_role = ""
    if project and tab_name not in ("newproject", "profile", "my-requests"):
        user_role = await _get_user_role(db, user, project)
        if not user_role:
            return HTMLResponse("<p>Not a project member</p>", status_code=403)

    # Per-tab minimum role checks (server-side enforcement)
    _tab_min_roles = {
        "backlog": "developer",
        "terminal": "developer",
        "transcriber": "developer",
        "pipeline": "developer",
        "queue": "developer",
        "join-requests": "owner",
        "members": "editor",
        # board, archive, agents, logs — viewer
    }
    tab_min_role = _tab_min_roles.get(tab_name, "viewer")
    if project and tab_name not in ("newproject", "profile", "my-requests"):
        my_rank = ROLE_RANK.get(user_role, -1)
        required_rank = ROLE_RANK.get(tab_min_role, 0)
        if my_rank < required_rank:
            return HTMLResponse("<p>Недостатньо прав для перегляду цієї вкладки</p>", status_code=403)

    ctx = _ctx(request, user, project=project, tab_name=tab_name, user_role=user_role)

    # Tab-specific data loading
    if tab_name in ("backlog", "board", "archive") and project:
        items = await _load_backlog(project, db)
        # Server-side search for archive
        if tab_name == "archive" and q:
            ql = q.lower()
            items = [i for i in items if
                     ql in (i.get("task") or i.get("title") or "").lower() or
                     ql in (i.get("description") or "").lower() or
                     ql in str(i.get("id", ""))]
        ctx["backlog_items"] = items
        ctx["artifact_counts"] = await _load_artifact_counts(project, db)
    if tab_name == "logs" and project:
        ctx["telemetry"] = await _load_telemetry(project)
    if tab_name == "agents" and project:
        ctx["agents_data"] = await _load_agents(project, db)
    if tab_name == "pipeline" and project:
        ctx["pipelines"] = await _load_pipelines(project)
    if tab_name == "join-requests" and project:
        _valid_jr_statuses = {"pending", "approved", "rejected", "cancelled", "all"}
        status_filter = request.query_params.get("status", "pending")
        if status_filter not in _valid_jr_statuses:
            status_filter = "pending"
        try:
            jr_offset = max(0, int(request.query_params.get("offset", "0")))
        except (ValueError, TypeError):
            jr_offset = 0
        jr_limit = 20

        # Owner access already enforced by ROLE_RANK check above (join-requests: "owner")
        proj = (await db.execute(select(Project).where(Project.slug == project))).scalar_one_or_none()
        if proj:
            from sqlalchemy.orm import selectinload
            base_q = select(JoinRequest).options(selectinload(JoinRequest.user)).where(JoinRequest.project_id == proj.id)
            if status_filter != "all":
                base_q = base_q.where(JoinRequest.status == status_filter)

            total_jr = (await db.execute(select(func.count()).select_from(base_q.subquery()))).scalar_one()
            jr_rows = (await db.execute(
                base_q.order_by(JoinRequest.created_at.desc()).offset(jr_offset).limit(jr_limit)
            )).scalars().all()

            # Pending count (always show badge)
            pending_count = (await db.execute(
                select(func.count()).select_from(
                    select(JoinRequest.id).where(
                        JoinRequest.project_id == proj.id,
                        JoinRequest.status == "pending",
                    ).subquery()
                )
            )).scalar_one()

            ctx["join_requests"] = jr_rows
            ctx["pending_count"] = pending_count
            ctx["has_more"] = (jr_offset + jr_limit) < total_jr
            ctx["status_filter"] = status_filter
            ctx["offset"] = jr_offset
            ctx["limit"] = jr_limit
        else:
            ctx["join_requests"] = []
            ctx["pending_count"] = 0
            ctx["has_more"] = False
            ctx["status_filter"] = "pending"
            ctx["offset"] = 0
            ctx["limit"] = 20

        # If partial=list requested (for HTMX list-only swap), return just the list
        if request.query_params.get("partial") == "list":
            return templates.TemplateResponse("partials/tabs/_join_requests_list.html", ctx)

    if tab_name == "members" and project:
        from sqlalchemy.orm import selectinload
        proj = (await db.execute(select(Project).where(Project.slug == project))).scalar_one_or_none()
        if proj:
            # Members sorted by ROLE_RANK desc, then created_at asc
            members_result = await db.execute(
                select(ProjectMembership)
                .options(selectinload(ProjectMembership.user))
                .where(ProjectMembership.project_id == proj.id)
            )
            members_all = members_result.scalars().all()

            from dashboard.auth.permissions import ROLE_RANK as RR
            members_all = sorted(members_all, key=lambda m: (-RR.get(m.role, 0), m.created_at))

            ctx["members"] = members_all

            # Pending requests (owner only)
            if user_role == "owner":
                pending_result = await db.execute(
                    select(JoinRequest)
                    .options(selectinload(JoinRequest.user))
                    .where(JoinRequest.project_id == proj.id, JoinRequest.status == "pending")
                    .order_by(JoinRequest.created_at.desc())
                )
                pending_requests = pending_result.scalars().all()
                ctx["pending_requests"] = pending_requests
                ctx["pending_count"] = len(pending_requests)
            else:
                ctx["pending_requests"] = []
                ctx["pending_count"] = 0
        else:
            ctx["members"] = []
            ctx["pending_requests"] = []
            ctx["pending_count"] = 0

        # If partial=list requested (for HTMX list-only swap), return just the list
        if request.query_params.get("partial") == "list":
            return templates.TemplateResponse("partials/tabs/_members_list.html", ctx)

    if tab_name == "my-requests":
        _valid_statuses = {"pending", "approved", "rejected", "cancelled", "all"}
        status_filter = request.query_params.get("status", "all")
        if status_filter not in _valid_statuses:
            status_filter = "all"
        try:
            mr_offset = max(0, int(request.query_params.get("offset", "0")))
        except (ValueError, TypeError):
            mr_offset = 0
        mr_limit = 20

        from sqlalchemy.orm import selectinload
        base_q = (
            select(JoinRequest)
            .options(selectinload(JoinRequest.project))
            .where(JoinRequest.user_id == user.id)
        )
        if status_filter != "all":
            base_q = base_q.where(JoinRequest.status == status_filter)

        total = (await db.execute(select(func.count()).select_from(base_q.subquery()))).scalar_one()
        rows = (await db.execute(
            base_q.order_by(JoinRequest.created_at.desc()).offset(mr_offset).limit(mr_limit)
        )).scalars().all()

        # Counts per status — single query with GROUP BY instead of 4 separate queries
        count_rows = (await db.execute(
            select(JoinRequest.status, func.count())
            .where(JoinRequest.user_id == user.id)
            .group_by(JoinRequest.status)
        )).all()
        counts = {st: 0 for st in ["pending", "approved", "rejected", "cancelled"]}
        for st, c in count_rows:
            counts[st] = c
        counts["all"] = sum(counts.values())

        ctx["my_requests"] = rows
        ctx["request_counts"] = counts
        ctx["has_more"] = (mr_offset + mr_limit) < total
        ctx["status_filter"] = status_filter
        ctx["offset"] = mr_offset
        ctx["limit"] = mr_limit

        if request.query_params.get("partial") == "list":
            return templates.TemplateResponse("partials/tabs/_my_requests_list.html", ctx)

    return templates.TemplateResponse(f"partials/tabs/_{tab_name}.html", ctx)


# ── Data loading helpers ────────────────────────────────────────────

async def _load_backlog(project: str, db: AsyncSession | None = None) -> list[dict]:
    """Load backlog items from DB for a project."""
    if not db:
        return []
    from dashboard.db.models.backlog import BacklogItem, BacklogItemImage
    from dashboard.db.models.project import Project
    from sqlalchemy.orm import selectinload

    proj = (await db.execute(select(Project).where(Project.slug == project))).scalar_one_or_none()
    if not proj:
        return []

    result = await db.execute(
        select(BacklogItem)
        .where(BacklogItem.project_id == proj.id)
        .options(selectinload(BacklogItem.images))
        .order_by(BacklogItem.sort_order, BacklogItem.sequence_number)
    )
    items = []
    for bi in result.scalars().all():
        images = []
        for img in (bi.images or []):
            if img.s3_key:
                images.append({"url": f"/api/projects/{project}/backlog/{bi.sequence_number}/images/{img.original_filename}"})
            elif img.local_path:
                images.append({"url": f"/api/projects/{project}/backlog/{bi.sequence_number}/images/{img.original_filename}"})
        items.append({
            "id": bi.sequence_number,
            "task": bi.title,
            "title": bi.title,
            "description": bi.description or "",
            "priority": bi.priority or "medium",
            "status": bi.status or "todo",
            "images": images,
        })
    return items


async def _load_telemetry(project: str) -> dict:
    try:
        from pathlib import Path
        from dashboard.helpers import BASE
        log_path = BASE / "dashboard" / "pipeline.log"
        if log_path.exists():
            lines = log_path.read_text("utf-8").strip().split("\n")[-200:]
            return {"lines": lines, "count": len(lines)}
    except Exception:
        pass
    return {"lines": [], "count": 0}


async def _load_agents(project: str, db=None) -> dict:
    """Load full agent data for a project (global + overrides) and skills."""
    from dashboard.db.models.agent_config import AgentConfig
    from dashboard.db.models.project import Project
    from dashboard.helpers import AGENTS, PROJECTS, BASE

    PIPELINE_AGENTS = [
        "project-manager", "business-analyst", "architect", "designer",
        "developer", "tester", "performance-reviewer",
    ]
    DEV_AGENTS = ["project-manager", "business-analyst", "architect", "developer", "tester"]
    AGENT_LABELS = {
        "project-manager": "PM",
        "business-analyst": "BA",
        "architect": "ARCH",
        "developer": "DEV",
        "tester": "QA",
        "designer": "Designer",
        "performance-reviewer": "Perf",
    }

    agents_map = {}

    if db:
        # Load global configs
        globals_result = await db.execute(
            select(AgentConfig).where(AgentConfig.project_id == None)
        )
        global_configs = {ac.agent_name: ac.instructions_md for ac in globals_result.scalars().all()}

        # Load project overrides
        project_configs = {}
        proj_result = await db.execute(select(Project).where(Project.slug == project))
        proj = proj_result.scalar_one_or_none()
        if proj:
            proj_overrides = await db.execute(
                select(AgentConfig).where(AgentConfig.project_id == proj.id)
            )
            project_configs = {ac.agent_name: ac.instructions_md for ac in proj_overrides.scalars().all()}

        all_agent_names = set(list(global_configs.keys()) + PIPELINE_AGENTS)
        for agent_name in sorted(all_agent_names):
            if agent_name in project_configs:
                agents_map[agent_name] = {"content": project_configs[agent_name], "source": "project"}
            elif agent_name in global_configs:
                agents_map[agent_name] = {"content": global_configs[agent_name], "source": "global"}
            else:
                agents_map[agent_name] = {"content": "", "source": "default"}

    # Load pipeline config for discovery stages
    discovery_stages = []
    cfg_path = PROJECTS / project / "pipeline-config.json"
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            raw_ds = cfg.get("discovery_stages", [])
            for s in raw_ds:
                if isinstance(s, str):
                    discovery_stages.append({"name": s, "agent": f"discovery-{s}", "description": ""})
                else:
                    discovery_stages.append(s)
        except Exception:
            pass

    # Load skills
    skills = _load_skills_data()

    return {
        "agents_map": agents_map,
        "dev_agents": DEV_AGENTS,
        "agent_labels": AGENT_LABELS,
        "discovery_stages": discovery_stages,
        "first_agent": DEV_AGENTS[0] if DEV_AGENTS else None,
        "skills": skills,
    }


async def _load_artifact_counts(project: str, db: AsyncSession | None = None) -> dict[str, int]:
    """Return {task_id: artifact_count} for badge rendering. Reads from DB."""
    if not db:
        return {}
    from sqlalchemy import func
    from dashboard.db.models.artifact import Artifact
    from dashboard.db.models.backlog import BacklogItem
    from dashboard.db.models.project import Project

    proj = (await db.execute(select(Project).where(Project.slug == project))).scalar_one_or_none()
    if not proj:
        return {}

    rows = (await db.execute(
        select(BacklogItem.sequence_number, func.count(Artifact.id))
        .join(Artifact, Artifact.backlog_item_id == BacklogItem.id)
        .where(BacklogItem.project_id == proj.id)
        .group_by(BacklogItem.sequence_number)
    )).all()

    return {str(seq): cnt for seq, cnt in rows}


async def _load_pipelines(project: str) -> list[dict]:
    # Will be populated from DB in future; for now return empty
    return []


def _load_skills_data() -> list[dict]:
    """Parse AGENTS.md and tessl.json for skill listings (same logic as agents router)."""
    import re
    from dashboard.helpers import BASE

    skills = []
    agents_md = BASE / "docs" / "AGENTS.md"
    tessl_json = BASE / "tessl.json"

    installed = {}
    if tessl_json.exists():
        try:
            data = json.loads(tessl_json.read_text())
            for tile, info in data.get("dependencies", {}).items():
                if tile.startswith("tessl/"):
                    continue
                installed[tile] = info.get("version", "")[:12]
        except Exception:
            pass

    if agents_md.exists():
        try:
            text = agents_md.read_text()
            current_section = "global"
            for line in text.split("\n"):
                if line.startswith("## "):
                    section = line[3:].strip().lower()
                    if "global" in section:
                        current_section = "global"
                    elif "backend" in section or ("dev agent" in section and "fastapi" in section):
                        current_section = "backend"
                    elif "frontend" in section or "react" in section or "next" in section:
                        current_section = "frontend"
                    elif "qa" in section or "test" in section:
                        current_section = "qa"
                    elif "product" in section or section.startswith("pm"):
                        current_section = "pm"
                    elif "business" in section or section.startswith("ba"):
                        current_section = "ba"
                    else:
                        current_section = section
                elif line.startswith("### "):
                    parts = line[4:].strip().split(" — ", 1)
                    skill_label = parts[0].strip()
                    skill_source = parts[1].strip() if len(parts) > 1 else ""
                    skill_desc = ""
                    idx = text.index(line)
                    after = text[idx + len(line):]
                    for next_line in after.split("\n"):
                        next_line = next_line.strip()
                        if next_line.startswith("@"):
                            parts2 = next_line.split(maxsplit=1)
                            if len(parts2) > 1:
                                raw_desc = parts2[1]
                                skill_desc = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', raw_desc)
                                if skill_desc:
                                    skill_desc = skill_desc[0].upper() + skill_desc[1:]
                            break
                        if next_line.startswith("##"):
                            break
                    is_installed = any(skill_source.split("/")[0] in tile for tile in installed) if "/" in skill_source else skill_source in installed
                    skills.append({
                        "name": skill_label,
                        "source": skill_source,
                        "description": skill_desc,
                        "agent": current_section,
                        "installed": is_installed,
                    })
        except Exception:
            pass

    return skills


# ── HTMX Partials: Task Artifacts ──────────────────────────────────

@router.get("/ui/partials/task-artifacts")
async def task_artifacts_partial(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    project: str = Query("", alias="project"),
    task_id: str = Query("", alias="task_id"),
):
    """Return artifacts list for a single task as HTML fragment."""
    from dashboard.db.models.artifact import Artifact
    from dashboard.db.models.backlog import BacklogItem
    from dashboard.db.models.project import Project

    if project:
        from dashboard.routers.projects import _check_project_access
        await _check_project_access(project, user, db, "viewer")

    artifacts = []
    proj = (await db.execute(select(Project).where(Project.slug == project))).scalar_one_or_none()
    if proj:
        # Find BacklogItem by sequence_number (file-based numeric ID)
        bi = (await db.execute(
            select(BacklogItem).where(
                BacklogItem.project_id == proj.id,
                BacklogItem.sequence_number == int(task_id),
            )
        )).scalar_one_or_none()

        if bi:
            result = await db.execute(
                select(
                    Artifact.id, Artifact.stage, Artifact.name,
                    Artifact.artifact_type, Artifact.mime_type,
                    Artifact.size_bytes, Artifact.local_path,
                    Artifact.content_text != None,  # noqa: E711 — boolean check without loading text
                ).where(
                    Artifact.backlog_item_id == bi.id,
                ).order_by(Artifact.stage, Artifact.created_at)
            )
            for row in result.all():
                a_id, stage, name, a_type, mime, size, local_path, has_text = row
                is_image = (mime or "").startswith("image/")
                is_html = name.endswith(".html") or name.endswith(".htm")
                artifacts.append({
                    "id": str(a_id),
                    "stage": stage or "",
                    "name": name,
                    "artifact_type": a_type,
                    "mime_type": mime or "",
                    "size_bytes": size,
                    "is_image": is_image,
                    "is_html": is_html,
                    "is_viewable": bool(has_text) or a_type == "text" or a_type == "code_changes",
                    "local_path": local_path or "",
                })

    ctx = _ctx(request, user, project=project)
    ctx["artifacts"] = artifacts
    ctx["task_id"] = task_id
    return templates.TemplateResponse("partials/_task_artifacts.html", ctx)


@router.get("/ui/partials/artifact-content/{artifact_id}")
async def artifact_content_partial(
    artifact_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    project: str = Query("", alias="project"),
):
    """Return a single artifact's content as HTML fragment."""
    import uuid as _uuid
    from dashboard.db.models.artifact import Artifact

    if project:
        from dashboard.routers.projects import _check_project_access
        await _check_project_access(project, user, db, "viewer")

    content = ""
    name = ""
    is_image = False
    image_src = ""
    try:
        art = await db.get(Artifact, _uuid.UUID(artifact_id))
        if art:
            name = art.name
            is_image = (art.mime_type or "").startswith("image/")

            if is_image:
                if art.local_path:
                    image_src = f"/api/artifacts/{artifact_id}/raw?project={project}"
                elif art.s3_key:
                    image_src = f"/api/artifacts/{artifact_id}/raw?project={project}"
            elif art.content_text:
                content = art.content_text
            elif art.local_path:
                try:
                    content = Path(art.local_path).read_text(encoding="utf-8")
                except Exception:
                    content = f"[Cannot read: {art.local_path}]"
            elif art.s3_key:
                try:
                    from dashboard.storage.manager import _get_s3
                    data = await _get_s3().download(art.s3_key)
                    content = data.decode("utf-8", errors="replace")
                except Exception:
                    content = f"[Cannot read from S3: {art.s3_key}]"
    except Exception:
        content = "[Artifact not found]"

    is_html = name.endswith(".html") or name.endswith(".htm")

    ctx = _ctx(request, user, project=project)
    ctx["artifact_content"] = content
    ctx["artifact_name"] = name
    ctx["artifact_id"] = artifact_id
    ctx["is_image"] = is_image
    ctx["is_html"] = is_html
    ctx["image_src"] = image_src
    return templates.TemplateResponse("partials/_artifact_content.html", ctx)


@router.get("/api/artifacts/{artifact_id}/raw")
async def artifact_raw(
    artifact_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    project: str = Query("", alias="project"),
):
    """Serve raw artifact binary (images, etc.)."""
    import uuid as _uuid
    from fastapi.responses import Response
    from dashboard.db.models.artifact import Artifact

    if project:
        from dashboard.routers.projects import _check_project_access
        await _check_project_access(project, user, db, "viewer")

    art = await db.get(Artifact, _uuid.UUID(artifact_id))
    if not art:
        return Response(status_code=404)

    # Text content stored in DB (includes HTML artifacts)
    if art.content_text:
        return Response(content=art.content_text.encode("utf-8"), media_type=art.mime_type or "text/plain")
    if art.local_path:
        p = Path(art.local_path)
        if p.exists():
            return Response(content=p.read_bytes(), media_type=art.mime_type or "application/octet-stream")
    if art.s3_key:
        from dashboard.storage.manager import _get_s3
        data = await _get_s3().download(art.s3_key)
        return Response(content=data, media_type=art.mime_type or "application/octet-stream")

    return Response(status_code=404)


# ── HTMX Partials: Agent Editor ──────────────────────────────────────

@router.get("/ui/partials/agent-editor/{agent_name}")
async def agent_editor_partial(
    agent_name: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    project: str = Query("", alias="project"),
):
    """Return the agent editor fragment for HTMX swap."""
    from dashboard.db.models.agent_config import AgentConfig
    from dashboard.db.models.project import Project
    from dashboard.helpers import safe_path_param

    agent_name = safe_path_param(agent_name)

    if project:
        from dashboard.routers.projects import _check_project_access
        await _check_project_access(project, user, db, "viewer")

    # Load agent content from DB
    content = ""
    source = "default"

    if project:
        proj_result = await db.execute(select(Project).where(Project.slug == project))
        proj = proj_result.scalar_one_or_none()

        if proj:
            # Check for project override first
            proj_agent = await db.execute(
                select(AgentConfig).where(
                    AgentConfig.project_id == proj.id,
                    AgentConfig.agent_name == agent_name,
                )
            )
            ac = proj_agent.scalar_one_or_none()
            if ac:
                content = ac.instructions_md
                source = "project"

        if source != "project":
            # Fall back to global
            global_agent = await db.execute(
                select(AgentConfig).where(
                    AgentConfig.project_id == None,
                    AgentConfig.agent_name == agent_name,
                )
            )
            ac = global_agent.scalar_one_or_none()
            if ac:
                content = ac.instructions_md
                source = "global"

    user_role = await _get_user_role(db, user, project) if project else ""
    ctx = _ctx(request, user, project=project, user_role=user_role)
    ctx["agent_name"] = agent_name
    ctx["agent_content"] = content
    ctx["agent_source"] = source

    return templates.TemplateResponse("partials/_agent_editor.html", ctx)


# ── HTMX Partials: Artifact View ─────────────────────────────────────

@router.get("/ui/partials/artifact-view/{task_id}/{filename}")
async def artifact_view_partial(
    task_id: str,
    filename: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    project: str = Query("", alias="project"),
):
    """Return artifact file content as HTML fragment."""
    from dashboard.helpers import get_ai_workflow_dir, safe_path_param

    task_id = safe_path_param(task_id)
    filename = safe_path_param(filename)

    if project:
        from dashboard.routers.projects import _check_project_access
        await _check_project_access(project, user, db, "viewer")

    content = ""
    if project:
        ai_dir = get_ai_workflow_dir(project)
        f = (ai_dir / "artifacts" / task_id / filename).resolve()
        base = (ai_dir / "artifacts").resolve()
        if str(f).startswith(str(base)) and f.exists():
            content = f.read_text(encoding="utf-8")

    ctx = _ctx(request, user, project=project)
    ctx["artifact_content"] = content
    ctx["artifact_filename"] = filename
    ctx["task_id"] = task_id

    return templates.TemplateResponse("partials/_artifact_view.html", ctx)


@router.get("/ui/partials/code-changes/{task_id}")
async def code_changes_partial(
    task_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    project: str = Query("", alias="project"),
):
    """Return code changes diff view as HTML fragment."""
    from dashboard.helpers import get_ai_workflow_dir, safe_path_param

    task_id = safe_path_param(task_id)

    if project:
        from dashboard.routers.projects import _check_project_access
        await _check_project_access(project, user, db, "viewer")

    files = []
    if project:
        ai_dir = get_ai_workflow_dir(project)
        changes_file = ai_dir / "artifacts" / task_id / "code-changes" / "changes.json"
        if changes_file.exists():
            try:
                data = json.loads(changes_file.read_text(encoding="utf-8"))
                files = data.get("files", [])
            except Exception:
                pass

    ctx = _ctx(request, user, project=project)
    ctx["code_files"] = files
    ctx["task_id"] = task_id

    return templates.TemplateResponse("partials/_code_changes.html", ctx)
