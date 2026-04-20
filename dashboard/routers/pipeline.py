"""Pipeline execution API routes.

POST /api/pipeline/start      — start a pipeline run
POST /api/pipeline/complete    — callback from agent (no auth, internal)
POST /api/pipeline/{id}/advance — "Next" button
POST /api/pipeline/{id}/return  — manual return
POST /api/pipeline/{id}/cancel  — cancel run
GET  /api/pipeline/{id}         — run status with stages
GET  /api/pipeline/active       — list active runs
"""
import logging
import os
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dashboard.auth.middleware import get_current_user
from dashboard.auth.utils import parse_uuid
from dashboard.db.engine import get_db
from dashboard.db.models.user import User
from dashboard.db.models.project import Project
from dashboard.db.models.backlog import BacklogItem
from dashboard.db.models.pipeline import PipelineDefinition, PipelineRun
from dashboard.services.pipeline_engine import pipeline_engine, PipelineError

logger = logging.getLogger("routers.pipeline")

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])

_PIPELINE_SECRET = os.getenv("PIPELINE_CALLBACK_SECRET", "")


# --- Schemas ---

class StartPipelineRequest(BaseModel):
    project_slug: str
    task_id: str  # backlog item UUID or task_id_display
    pipeline_id: str | None = None  # pipeline definition UUID; if None, uses default
    auto_advance: bool = False
    branch_strategy: Literal["current", "new"] | None = None
    branch_name: str | None = Field(default=None, max_length=200)

    @field_validator("branch_name")
    @classmethod
    def validate_branch_name(cls, v: str | None, info) -> str | None:
        if v is None:
            return v
        from dashboard.services.git_manager import GitManager, GitError
        try:
            return GitManager.validate_branch_name(v)
        except GitError as e:
            raise ValueError(str(e))


class CompleteStageRequest(BaseModel):
    pipeline_run_id: str
    node_id: str
    status: str = Field(pattern="^(completed|failed|returned)$")
    artifacts: list[dict] = []  # [{filename, path}]
    message: str = ""
    return_to: str | None = None
    secret: str | None = None


# --- Helpers ---

async def _resolve_backlog_item(db: AsyncSession, project: Project, task_id: str) -> BacklogItem:
    """Find backlog item by UUID or task_id_display."""
    try:
        item_uuid = uuid.UUID(task_id)
        item = await db.get(BacklogItem, item_uuid)
    except ValueError:
        result = await db.execute(
            select(BacklogItem).where(
                BacklogItem.project_id == project.id,
                BacklogItem.task_id_display == task_id,
            )
        )
        item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return item


async def _get_pipeline_def(db: AsyncSession, project: Project, pipeline_id: str | None) -> PipelineDefinition:
    """Get pipeline definition by ID or default.

    If pipeline_id refers to a GlobalPipelineTemplate, creates a JIT project-level
    PipelineDefinition so PipelineRun has a valid FK.
    Falls back to active global template if no project pipeline exists.
    """
    from dashboard.db.models.pipeline import GlobalPipelineTemplate

    if pipeline_id:
        pid = parse_uuid(pipeline_id, "pipeline_id")
        # Try project-level first
        pd = await db.get(PipelineDefinition, pid)
        if pd:
            return pd
        # Try global template
        gt = await db.get(GlobalPipelineTemplate, pid)
        if gt:
            return await _jit_copy_global(db, project, gt)
    else:
        # Try project default
        result = await db.execute(
            select(PipelineDefinition).where(
                PipelineDefinition.project_id == project.id,
                PipelineDefinition.is_default == True,
            )
        )
        pd = result.scalar_one_or_none()
        if pd:
            return pd
        # Fall back to active global template
        gt_result = await db.execute(
            select(GlobalPipelineTemplate).where(GlobalPipelineTemplate.is_active == True)
        )
        gt = gt_result.scalar_one_or_none()
        if gt:
            return await _jit_copy_global(db, project, gt)

    raise HTTPException(status_code=404, detail="Pipeline definition not found")


async def _jit_copy_global(db: AsyncSession, project: Project, gt) -> PipelineDefinition:
    """Create a hidden project-level PipelineDefinition from a global template for FK purposes."""
    pd = PipelineDefinition(
        project_id=project.id,
        name=gt.name,
        is_default=False,
        graph_json=gt.graph_json,
        stages_order=gt.stages_order,
        discovery_stages=gt.discovery_stages,
        final_task_status=gt.final_task_status,
    )
    db.add(pd)
    await db.flush()
    return pd


async def _check_run_access(db: AsyncSession, user: User, run_id: uuid.UUID, min_role: str = "editor") -> PipelineRun:
    """Load a PipelineRun and verify the user has access to its project.

    Raises 404 if the run doesn't exist, 403 if the user lacks permission.
    *min_role* specifies the minimum role required (default: 'editor' for mutations).
    Use min_role='developer' for read-only access, 'editor' for mutations.
    """
    from dashboard.auth.permissions import require_project_access_or_raise

    run = await db.get(PipelineRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Pipeline run not found")

    project = await db.get(Project, run.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    await require_project_access_or_raise(db, user, project, min_role)
    return run


# --- Routes ---

@router.post("/start")
async def start_pipeline(
    body: StartPipelineRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Start a pipeline run for a task. Requires editor+ role on project."""
    # Resolve project
    result = await db.execute(select(Project).where(Project.slug == body.project_slug))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check permission (editor or owner)
    from dashboard.auth.permissions import require_project_access_or_raise
    await require_project_access_or_raise(db, user, project, "editor")

    backlog_item = await _resolve_backlog_item(db, project, body.task_id)
    pipeline_def = await _get_pipeline_def(db, project, body.pipeline_id)

    try:
        run = await pipeline_engine.start_pipeline(
            db=db,
            project=project,
            backlog_item=backlog_item,
            pipeline_def=pipeline_def,
            user_id=user.id,
            auto_advance=body.auto_advance,
            branch_strategy=body.branch_strategy,
            branch_name=body.branch_name,
        )
    except PipelineError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "pipeline_run_id": str(run.id),
        "status": run.status,
        "git_branch": run.git_branch,
        "current_stage": run.current_stage,
    }


@router.post("/complete")
async def complete_stage(body: CompleteStageRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Callback from agent when stage is done. Restricted to localhost."""
    # Security: only accept from localhost
    client_host = request.client.host if request.client else ""
    if client_host not in ("127.0.0.1", "::1", "localhost"):
        raise HTTPException(status_code=403, detail="Callback only allowed from localhost")

    # Optional shared secret for extra security
    if _PIPELINE_SECRET and body.secret != _PIPELINE_SECRET:
        raise HTTPException(status_code=403, detail="Invalid callback secret")

    run_id = parse_uuid(body.pipeline_run_id, "pipeline_run_id")

    try:
        result = await pipeline_engine.complete_stage(
            db=db,
            pipeline_run_id=run_id,
            node_id=body.node_id,
            status=body.status,
            reported_artifacts=body.artifacts,
            message=body.message,
            return_to=body.return_to,
        )
    except PipelineError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return result


@router.post("/{run_id}/advance")
async def advance_pipeline(
    run_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Advance to the next stage. 'Next' button handler."""
    rid = parse_uuid(run_id, "run_id")
    await _check_run_access(db, user, rid, min_role="editor")

    try:
        result = await pipeline_engine.advance_pipeline(db=db, pipeline_run_id=rid, user_id=user.id)
    except PipelineError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return result


@router.post("/{run_id}/cancel")
async def cancel_pipeline(
    run_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a running pipeline."""
    rid = parse_uuid(run_id, "run_id")
    await _check_run_access(db, user, rid, min_role="editor")

    try:
        await pipeline_engine.cancel_pipeline(db=db, pipeline_run_id=rid, user_id=user.id)
    except PipelineError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"ok": True}


@router.get("/active")
async def list_active_pipelines(
    project_slug: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List active pipeline runs. Only returns runs for projects the user can access (developer+)."""
    from sqlalchemy import or_
    from dashboard.auth.permissions import ROLE_RANK
    from dashboard.db.models.project import ProjectMembership

    # Single JOIN query: running pipelines + project + membership check
    query = (
        select(PipelineRun, Project)
        .join(Project, PipelineRun.project_id == Project.id)
        .outerjoin(
            ProjectMembership,
            (ProjectMembership.project_id == Project.id)
            & (ProjectMembership.user_id == user.id),
        )
        .where(
            PipelineRun.status == "running",
            or_(
                ProjectMembership.role.in_(["developer", "editor", "owner"]),
                # Public projects: implicit viewer can't see pipeline (needs developer+)
                # so we don't include public without membership here
            ),
        )
    )

    if project_slug:
        query = query.where(Project.slug == project_slug)

    query = query.order_by(PipelineRun.started_at.desc())
    result = await db.execute(query)
    rows = result.all()

    return {
        "runs": [
            {
                "id": str(r.id),
                "project_id": str(r.project_id),
                "status": r.status,
                "current_stage": r.current_stage,
                "git_branch": r.git_branch,
                "started_at": r.started_at.isoformat() if r.started_at else None,
            }
            for r, _ in rows
        ]
    }


@router.get("/project-progress/{project_slug}")
async def project_pipeline_progress(
    project_slug: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get pipeline stage progress for tasks based on existing artifacts."""
    from dashboard.db.models.artifact import Artifact

    result = await db.execute(select(Project).where(Project.slug == project_slug))
    project = result.scalar_one_or_none()
    if not project:
        return {"items": {}}

    # Get all non-archived tasks
    from dashboard.db.models.backlog import BacklogItem
    tasks = (await db.execute(
        select(BacklogItem).where(
            BacklogItem.project_id == project.id,
            BacklogItem.status.notin_(["backlog", "archived"]),
        )
    )).scalars().all()

    # Default pipeline stages order
    default_stages = ["PM", "PM_REVIEW", "BA", "BA_REVIEW", "DESIGN",
                      "DEV", "DEV_REVIEW", "QA", "QA_REVIEW", "PERF", "COMMIT"]

    items = {}
    for bi in tasks:
        # Get distinct stages that have artifacts
        completed_stages = set((await db.execute(
            select(Artifact.stage).where(Artifact.backlog_item_id == bi.id).distinct()
        )).scalars().all())

        if not completed_stages:
            continue

        stages = []
        for s in default_stages:
            stages.append({
                "stage": s,
                "status": "completed" if s in completed_stages else "pending",
            })

        items[str(bi.id)] = {"stages": stages}

    return {"items": items}


@router.get("/git-branch/{project_slug}")
async def get_git_branch(
    project_slug: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get current git branch info for Run Pipeline modal."""
    from dashboard.auth.permissions import require_project_access_or_raise
    from dashboard.services.git_manager import git_manager

    result = await db.execute(select(Project).where(Project.slug == project_slug))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    await require_project_access_or_raise(db, user, project, "editor")

    from dashboard.services.instance_paths import resolve_local_path
    instance_repo_path = await resolve_local_path(db, project)
    return await git_manager.get_branch_info(instance_repo_path, project.prefix)


class CreateBranchRequest(BaseModel):
    branch_name: str = Field(max_length=200)

    @field_validator("branch_name")
    @classmethod
    def validate_branch_name(cls, v: str) -> str:
        from dashboard.services.git_manager import GitManager, GitError
        try:
            return GitManager.validate_branch_name(v)
        except GitError as e:
            raise ValueError(str(e))


@router.post("/git-branch/{project_slug}/create")
async def create_git_branch(
    project_slug: str,
    body: CreateBranchRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new git branch before starting pipeline."""
    from dashboard.auth.permissions import require_project_access_or_raise
    from dashboard.services.git_manager import git_manager, GitError

    result = await db.execute(select(Project).where(Project.slug == project_slug))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    await require_project_access_or_raise(db, user, project, "editor")

    from dashboard.services.instance_paths import resolve_local_path
    instance_repo_path = await resolve_local_path(db, project)
    if not instance_repo_path:
        raise HTTPException(status_code=400, detail="Project has no repository on this dashboard instance")

    try:
        branch = await git_manager.create_named_branch(instance_repo_path, body.branch_name)
        return {"ok": True, "branch": branch}
    except GitError as e:
        logger.warning("create_git_branch failed for %s: %s", project_slug, e)
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{run_id}")
async def get_pipeline_run(
    run_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get pipeline run status. Requires developer+ role on the project."""
    rid = parse_uuid(run_id, "run_id")

    # Check read access (developer+)
    await _check_run_access(db, user, rid, min_role="developer")

    try:
        return await pipeline_engine.get_run_status(db=db, pipeline_run_id=rid)
    except PipelineError as e:
        raise HTTPException(status_code=404, detail=str(e))
