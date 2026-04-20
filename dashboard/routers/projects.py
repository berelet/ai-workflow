"""Project-related API routes.

Extracted from server.py — all /api/projects/* endpoints plus
/api/browse, /uploads/*, /favicon.svg.
"""
import json
import re
import shutil
import subprocess
import uuid
from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from typing import Literal
from pydantic import BaseModel

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dashboard.auth.middleware import get_current_user
from dashboard.auth.permissions import require_viewer, require_editor, require_owner
from dashboard.db.engine import get_db
from dashboard.db.models.user import User
from dashboard.db.models.project import Project, ProjectMembership
from dashboard.db.models.pipeline import PipelineDefinition
from dashboard.services.instance_paths import resolve_local_path
from dashboard.helpers import (
    BASE,
    PROJECTS,
    UPLOADS,
    AGENTS,
    read_md,
    write_md,
    get_ai_workflow_dir,
    parse_pipeline,
    safe_path_param,
)

router = APIRouter(tags=["projects"])


def _safe_name(name: str) -> str:
    """Validate project name param in every endpoint to prevent path traversal."""
    return safe_path_param(name)


def _safe_id(val: str) -> str:
    """Validate task_id or pl_id path param."""
    return safe_path_param(val)


async def _check_project_access(name: str, user: User, db: AsyncSession, min_role: str = "viewer") -> None:
    """Check project access. Works for both DB and file-based projects.
    For DB projects: uses unified require_project_access_or_raise (no superadmin bypass).
    For file-only projects (no DB record): only superadmin can access.
    Raises HTTPException on denied access."""
    from dashboard.auth.permissions import _resolve_project, require_project_access_or_raise
    from fastapi import HTTPException

    project = await _resolve_project(db, name)
    if project:
        await require_project_access_or_raise(db, user, project, min_role)
    else:
        # File-only project (no DB record yet) — only superadmin can access.
        # This is the legacy path; once all projects are migrated to DB, this fallback goes away.
        if not user.is_superadmin:
            raise HTTPException(status_code=403, detail="Access denied")


PIPELINE_AGENTS = [
    "project-manager", "business-analyst", "architect", "designer",
    "developer", "tester", "performance-reviewer",
]
DISCOVERY_AGENTS = ["discovery"]


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class NewProject(BaseModel):
    name: str
    description: str = ""
    stack: str = ""
    repo_path: str = ""
    initial_task: str = ""
    visibility: Literal["public", "private"] = "public"


class BindLocalRequest(BaseModel):
    repo_path: str


class BacklogItem(BaseModel):
    task: str = ""
    description: str | None = None
    priority: str | None = None
    status: str | None = None


class PipelineUpdate(BaseModel):
    content: str


class InstructionsUpdate(BaseModel):
    content: str


class DeployRequest(BaseModel):
    bump: str = "patch"


class BaseBranchUpdate(BaseModel):
    base_branch: str


class BranchSwitchRequest(BaseModel):
    branch: str
    force: bool = False


# ---------------------------------------------------------------------------
# Internal helpers (not exported — only used by this router)
# ---------------------------------------------------------------------------

def sync_backlog_from_pipeline(name: str):
    """Legacy pipeline.md → backlog sync. No-op: backlog is now DB-backed."""
    pass


def _migrate_legacy_pipeline(name: str) -> dict:
    p = PROJECTS / name / "pipeline-config.json"
    stages = ["PM", "PM_REVIEW", "BA", "BA_REVIEW", "DESIGN",
              "DEV", "DEV_REVIEW", "QA", "QA_REVIEW", "PERF", "COMMIT"]
    if p.exists():
        cfg = json.loads(p.read_text(encoding="utf-8"))
        stages = cfg.get("stages", stages)

    nodes = {}
    x_pos = 100
    for i, stage in enumerate(stages):
        node_id = str(i + 1)
        nodes[node_id] = {
            "id": int(node_id),
            "name": "agent",
            "data": {"agent": stage, "type": "reviewer" if "REVIEW" in stage else "agent"},
            "class": "agent-node",
            "html": f'<div class="box"><span>{stage}</span>'
                    f'<span class="node-type-badge">'
                    f'{"Reviewer" if "REVIEW" in stage or stage == "PERF" else "Agent"}'
                    f'</span></div>',
            "typenode": False,
            "inputs": {"input_1": {"connections": [{"node": str(i), "input": "output_1"}]}} if i > 0 else {},
            "outputs": {"output_1": {"connections": [{"node": str(i + 2), "output": "input_1"}]}} if i < len(stages) - 1 else {},
            "pos_x": x_pos,
            "pos_y": 200,
        }
        x_pos += 250

    return {
        "id": "default",
        "name": "Default Pipeline",
        "graph": {
            "drawflow": {
                "Home": {
                    "data": nodes,
                }
            }
        },
    }


# ---------------------------------------------------------------------------
# Favicon & uploads
# ---------------------------------------------------------------------------

@router.get("/favicon.svg")
def serve_favicon():
    """Favicon served without auth — browsers request it on all pages including login."""
    return FileResponse(Path(__file__).parent.parent / "favicon.svg", media_type="image/svg+xml")


@router.get("/uploads/{name}/{filename}")
def serve_upload(name: str, filename: str, user: User = Depends(get_current_user)):
    f = (UPLOADS / name / filename).resolve()
    if not str(f).startswith(str(UPLOADS.resolve())):
        return JSONResponse({"error": "invalid path"}, status_code=400)
    if f.exists():
        return FileResponse(f)
    return JSONResponse({"error": "not found"}, status_code=404)


# ---------------------------------------------------------------------------
# Browse (folder picker)
# ---------------------------------------------------------------------------

@router.get("/api/browse")
def browse_dirs(path: str = "~", user: User = Depends(get_current_user)):
    """List subdirectories for folder picker UI.

    Restricted to a whitelist of safe base paths to prevent arbitrary
    filesystem enumeration.
    """
    target = Path(path).expanduser().resolve()

    # Whitelist of allowed base directories
    user_home = Path("~").expanduser().resolve()
    allowed_bases = [
        Path("/").resolve(),
        user_home,
        Path("/home").resolve(),
        Path("/var/www").resolve(),
        Path("/opt").resolve(),
        Path("/srv").resolve(),
        PROJECTS.resolve(),
    ]
    if not any(
        target == base or str(target).startswith(str(base).rstrip("/") + "/")
        for base in allowed_bases
    ):
        return {"error": "Access denied: path outside allowed directories", "path": str(target), "dirs": []}

    if not target.is_dir():
        return {"error": "Not a directory", "path": str(target), "dirs": []}
    dirs: list[str] = []
    try:
        for entry in sorted(target.iterdir()):
            if entry.is_dir() and not entry.name.startswith('.'):
                dirs.append(entry.name)
    except PermissionError:
        pass
    return {"path": str(target), "dirs": dirs}


# ---------------------------------------------------------------------------
# Projects CRUD
# ---------------------------------------------------------------------------

@router.get("/api/projects/{name}/updated-at")
async def project_updated_at(name: str, user: User = Depends(get_current_user), db=Depends(get_db)):
    """Returns last modification timestamp for sync polling."""
    name = _safe_name(name)
    await _check_project_access(name, user, db, "viewer")
    ai_dir = get_ai_workflow_dir(name)
    # Find max mtime across key files
    max_mtime = 0
    for fname in ["backlog.json", "pipeline.md", "project.md"]:
        p = ai_dir / fname
        if p.exists():
            max_mtime = max(max_mtime, p.stat().st_mtime)
    from datetime import datetime, timezone
    ts = datetime.fromtimestamp(max_mtime, tz=timezone.utc).isoformat() if max_mtime else None
    return {"updated_at": ts}


@router.get("/api/projects")
async def list_projects(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    from sqlalchemy import select, or_
    from dashboard.db.models.project import Project, ProjectMembership

    # Membership projects + public projects (no duplicates), same for all users
    result = await db.execute(
        select(Project.slug)
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
    return [row[0] for row in result.all()]


@router.post("/api/projects")
async def create_project(body: NewProject, user: User = Depends(get_current_user), db=Depends(get_db)):
    from dashboard.db.models.project import Project, ProjectMembership

    slug = re.sub(r'[^a-z0-9\-]', '-', body.name.lower()).strip('-')
    slug = re.sub(r'-+', '-', slug)
    if not slug:
        return JSONResponse({"error": "Invalid project name"}, status_code=400)
    slug = safe_path_param(slug)  # reject any .. or /

    # Generate a short prefix from the slug (first 4 alpha chars, uppercased)
    alpha_chars = [c for c in slug if c.isalpha()]
    prefix = ("".join(alpha_chars[:4]) or slug[:4]).upper()
    # Ensure prefix uniqueness by appending digits if needed
    from sqlalchemy import select
    base_prefix = prefix
    counter = 1
    while True:
        existing = await db.execute(select(Project).where(Project.prefix == prefix))
        if not existing.scalar_one_or_none():
            break
        prefix = f"{base_prefix[:3]}{counter}"
        counter += 1

    p = PROJECTS / slug
    if p.exists():
        return {"error": "Проект уже существует"}
    p.mkdir(parents=True)
    # Determine ai_dir and base_branch
    base_branch = "main"
    if body.repo_path:
        repo = Path(body.repo_path).resolve()
        if not repo.is_dir():
            return JSONResponse({"error": "repo_path does not exist or is not a directory"}, status_code=400)
        ai_dir = repo / ".ai-workflow"
        cfg = {
            "stages": ["PM", "PM_REVIEW", "BA", "BA_REVIEW", "DESIGN",
                        "DEV", "DEV_REVIEW", "QA", "QA_REVIEW", "PERF", "COMMIT"],
            "project_dir": body.repo_path,
        }
        # Detect base branch from the existing repo (best-effort)
        if (repo / ".git").exists():
            try:
                # Prefer remote default branch (refs/remotes/origin/HEAD)
                proc = subprocess.run(
                    ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
                    cwd=str(repo), capture_output=True, text=True, timeout=5,
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    # Output like "origin/main" → take the part after the slash
                    raw = proc.stdout.strip()
                    base_branch = raw.split("/", 1)[1] if "/" in raw else raw
                else:
                    # Fall back to current branch
                    proc2 = subprocess.run(
                        ["git", "branch", "--show-current"],
                        cwd=str(repo), capture_output=True, text=True, timeout=5,
                    )
                    if proc2.returncode == 0 and proc2.stdout.strip():
                        base_branch = proc2.stdout.strip()
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                pass
    else:
        ai_dir = p
        cfg = {
            "stages": ["PM", "PM_REVIEW", "BA", "BA_REVIEW", "DESIGN",
                        "DEV", "DEV_REVIEW", "QA", "QA_REVIEW", "PERF", "COMMIT"],
        }
    ai_dir.mkdir(parents=True, exist_ok=True)
    (p / "pipeline-config.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    md = f"# {body.name}\n\n## Описание\n{body.description}\n\n## Стек\n{body.stack}\n"
    if body.repo_path:
        md += f"\n## Путь к проекту\n`{body.repo_path}`\n"
    write_md(ai_dir / "project.md", md)
    write_md(ai_dir / "pipeline.md", "")

    # Create DB record for the project and add the creating user as owner
    # NOTE: repo_path is no longer written to Project — it's stored as a per-instance
    # binding via set_local_path so multiple dashboards can host the same project
    # at different filesystem paths.
    db_project = Project(
        slug=slug,
        prefix=prefix,
        name=body.name,
        description=body.description,
        stack=body.stack,
        visibility=body.visibility,
        base_branch=base_branch,
        created_by=user.id,
    )
    db.add(db_project)
    await db.flush()  # get the generated project id

    membership = ProjectMembership(
        user_id=user.id,
        project_id=db_project.id,
        role="owner",
    )
    db.add(membership)

    # Bind the on-disk path to THIS dashboard instance only
    if body.repo_path:
        from dashboard.services.instance_paths import set_local_path
        await set_local_path(db, db_project.id, body.repo_path)

    # Copy active global pipeline template to project
    await _ensure_default_pipeline(db, db_project)

    # Initial backlog item (if provided)
    if body.initial_task:
        from dashboard.db.models.backlog import BacklogItem as BacklogItemModel
        db_project.task_counter = 1
        db.add(BacklogItemModel(
            project_id=db_project.id,
            sequence_number=1,
            task_id_display=f"{prefix}-1",
            title=body.initial_task,
            description=body.description,
            priority="high",
            status="todo",
            sort_order=1,
            created_by=user.id,
        ))

    await db.commit()

    return {"ok": True, "slug": slug}


@router.post("/api/projects/{slug}/bind-local")
async def bind_local(
    slug: str,
    body: BindLocalRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Bind an existing DB project to a local folder on THIS dashboard instance.

    Used when a project exists in the shared catalog but has no on-disk presence
    on the current dashboard. After binding, the dashboard can read files and
    run pipelines against the repo.

    Requires ≥ developer role on the project (file-touching action).
    """
    slug = _safe_name(slug)
    await _check_project_access(slug, user, db, "developer")

    proj = (await db.execute(
        select(Project).where(Project.slug == slug)
    )).scalar_one_or_none()
    if not proj:
        return JSONResponse({"error": "Project not found"}, status_code=404)

    repo = Path(body.repo_path).expanduser().resolve()
    if not repo.is_dir():
        return JSONResponse(
            {"error": "repo_path does not exist or is not a directory"},
            status_code=400,
        )

    # Detect base branch from .git (best-effort, falls back to project's stored value)
    base_branch = proj.base_branch or "main"
    if (repo / ".git").exists():
        try:
            head_proc = subprocess.run(
                ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"],
                cwd=str(repo), capture_output=True, text=True, timeout=5,
            )
            if head_proc.returncode == 0 and head_proc.stdout.strip():
                raw = head_proc.stdout.strip()
                base_branch = raw.split("/", 1)[1] if "/" in raw else raw
            else:
                cur_proc = subprocess.run(
                    ["git", "branch", "--show-current"],
                    cwd=str(repo), capture_output=True, text=True, timeout=5,
                )
                if cur_proc.returncode == 0 and cur_proc.stdout.strip():
                    base_branch = cur_proc.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

    # Local registry dir (PROJECTS/<slug>/pipeline-config.json) — required by
    # legacy get_ai_workflow_dir() lookup, which reads project_dir from this file.
    registry = PROJECTS / slug
    registry.mkdir(parents=True, exist_ok=True)
    cfg = {
        "stages": ["PM", "PM_REVIEW", "BA", "BA_REVIEW", "DESIGN",
                    "DEV", "DEV_REVIEW", "QA", "QA_REVIEW", "PERF", "COMMIT"],
        "project_dir": str(repo),
    }
    (registry / "pipeline-config.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8",
    )

    # Ensure .ai-workflow skeleton exists in the repo so file-based code paths work
    ai_dir = repo / ".ai-workflow"
    ai_dir.mkdir(parents=True, exist_ok=True)

    from dashboard.services.instance_paths import set_local_path
    await set_local_path(db, proj.id, str(repo))
    await db.commit()

    return {
        "ok": True,
        "slug": slug,
        "local_path": str(repo),
        "base_branch": base_branch,
    }


def _git_dirty_status(repo_path: str) -> dict:
    """Return dict with dirty files and unpushed commits for a repo. Empty lists if clean."""
    result = {"dirty": [], "unpushed": []}
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=repo_path, capture_output=True, text=True, timeout=5,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            result["dirty"] = [
                line.strip() for line in proc.stdout.splitlines() if line.strip()
            ]
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    try:
        # @{u} fails if no upstream tracking branch — treat as "no unpushed"
        proc = subprocess.run(
            ["git", "log", "@{u}..HEAD", "--oneline"],
            cwd=repo_path, capture_output=True, text=True, timeout=5,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            result["unpushed"] = [
                line.strip() for line in proc.stdout.splitlines() if line.strip()
            ]
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    return result


@router.delete("/api/projects/{name}")
async def delete_project(
    name: str,
    force: bool = False,
    user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    name = _safe_name(name)
    await _check_project_access(name, user, db, "owner")
    p = PROJECTS / name
    if not p.exists():
        return {"error": "Проект не найден"}

    # Read config to find external project_dir (legacy file-based) — needed for both branches below
    cfg_path = p / "pipeline-config.json"
    project_dir = None
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text("utf-8"))
            project_dir = cfg.get("project_dir")
        except Exception:
            pass

    # Look up DB project to determine workspace-managed vs external
    from dashboard.routers.git_ops import _get_workspaces_dir
    from dashboard.services.instance_paths import resolve_local_path, unset_local_path
    db_project = (await db.execute(
        select(Project).where(Project.slug == name)
    )).scalar_one_or_none()

    # Resolve actual on-disk path for THIS dashboard instance
    instance_repo_path = await resolve_local_path(db, db_project) if db_project else None

    is_workspace_managed = False
    if db_project and instance_repo_path:
        workspaces_dir = await _get_workspaces_dir(db)
        try:
            repo_resolved = Path(instance_repo_path).resolve()
            ws_resolved = workspaces_dir.resolve()
            is_workspace_managed = str(repo_resolved).startswith(str(ws_resolved) + "/") or str(repo_resolved) == str(ws_resolved)
        except Exception:
            is_workspace_managed = False

    if is_workspace_managed and not force:
        # Check git state — block if dirty or has unpushed commits
        status = _git_dirty_status(instance_repo_path)
        if status["dirty"] or status["unpushed"]:
            return JSONResponse(
                status_code=409,
                content={
                    "error": "uncommitted_changes",
                    "message": "Project has uncommitted changes or unpushed commits. Pass ?force=true to delete anyway.",
                    "dirty": status["dirty"],
                    "unpushed": status["unpushed"],
                },
            )

    # Remove project registry entry
    shutil.rmtree(p)

    if is_workspace_managed:
        # Workspace-managed: delete the entire cloned repo folder
        try:
            shutil.rmtree(instance_repo_path)
        except OSError:
            # Don't fail the whole delete — registry is already gone
            pass
    elif project_dir:
        # External: only remove .ai-workflow inside, leave user's code untouched
        ai_dir = Path(project_dir) / ".ai-workflow"
        if ai_dir.exists():
            shutil.rmtree(ai_dir)

    # DB cleanup
    if db_project:
        # Unbind path on this instance only (other instances may still own this project)
        await unset_local_path(db, db_project.id)
        # If no other instance has a binding for this project, delete the Project entirely.
        # Otherwise, just keep the Project record so other instances aren't broken.
        from dashboard.db.models.dashboard_instance import InstanceProjectBinding
        other_bindings = (await db.execute(
            select(InstanceProjectBinding).where(InstanceProjectBinding.project_id == db_project.id).limit(1)
        )).scalar_one_or_none()
        if not other_bindings:
            await db.delete(db_project)
        await db.commit()

    return {"ok": True}


@router.get("/api/projects/{name}/branch-status")
async def get_branch_status(
    name: str,
    user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """Live branch status: current working tree branch + base_branch + dirty/unpushed.

    Used by the topbar branch badge to show the actual on-disk state.
    Returns null current_branch if there's no repo on disk.
    """
    name = _safe_name(name)
    await _check_project_access(name, user, db, "viewer")

    db_project = (await db.execute(
        select(Project).where(Project.slug == name)
    )).scalar_one_or_none()
    if not db_project:
        return JSONResponse({"error": "project_not_found"}, status_code=404)

    from dashboard.services.instance_paths import resolve_local_path
    instance_repo_path = await resolve_local_path(db, db_project)

    base_branch = db_project.base_branch or "main"
    if not instance_repo_path or not (Path(instance_repo_path) / ".git").exists():
        return {
            "has_repo": False,
            "current_branch": None,
            "base_branch": base_branch,
            "dirty": [],
            "unpushed": [],
        }

    from dashboard.services.git_manager import git_manager
    current_branch = await git_manager.get_current_branch(instance_repo_path)
    state = await git_manager.get_dirty_state(instance_repo_path)

    return {
        "has_repo": True,
        "current_branch": current_branch or None,
        "base_branch": base_branch,
        "dirty": state["dirty"],
        "unpushed": state["unpushed"],
    }


@router.patch("/api/projects/{name}/branch")
async def switch_project_branch(
    name: str,
    body: BranchSwitchRequest,
    user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """Checkout the given branch in the project's working tree AND update base_branch.

    The branch is treated as both the current working branch and the base for future
    task branches / merges. If the working tree has uncommitted changes or unpushed
    commits, returns 409 with details unless force=true.

    Requires editor or higher.
    """
    name = _safe_name(name)
    await _check_project_access(name, user, db, "editor")

    db_project = (await db.execute(
        select(Project).where(Project.slug == name)
    )).scalar_one_or_none()
    if not db_project:
        return JSONResponse({"error": "project_not_found"}, status_code=404)

    from dashboard.services.instance_paths import resolve_local_path
    instance_repo_path = await resolve_local_path(db, db_project)

    if not instance_repo_path or not (Path(instance_repo_path) / ".git").exists():
        # No repo on disk — just update the DB setting
        from dashboard.services.git_manager import GitManager
        try:
            validated = GitManager.validate_branch_name(body.branch.strip())
        except Exception as e:
            return JSONResponse({"error": "invalid_branch_name", "message": str(e)}, status_code=400)
        db_project.base_branch = validated
        await db.commit()
        return {"ok": True, "branch": validated, "current_branch": None, "checked_out": False}

    from dashboard.services.git_manager import git_manager, GitError
    try:
        result = await git_manager.checkout_branch(
            repo_path=instance_repo_path,
            branch=body.branch.strip(),
            force=body.force,
        )
    except GitError as e:
        if str(e) == "dirty_or_unpushed":
            return JSONResponse(
                status_code=409,
                content={
                    "error": "dirty_or_unpushed",
                    "message": "Working tree has uncommitted changes or unpushed commits.",
                    "dirty": getattr(e, "dirty", []),
                    "unpushed": getattr(e, "unpushed", []),
                },
            )
        return JSONResponse({"error": "checkout_failed", "message": str(e)}, status_code=400)

    db_project.base_branch = result["branch"]
    await db.commit()
    return {
        "ok": True,
        "branch": result["branch"],
        "current_branch": result["branch"],
        "checked_out": True,
    }


@router.get("/api/projects/{name}")
async def get_project(name: str, user: User = Depends(get_current_user), db=Depends(get_db)):
    from dashboard.db.models.project import Project
    from dashboard.db.models.backlog import BacklogItem as BacklogItemModel
    from sqlalchemy.orm import selectinload

    name = _safe_name(name)
    await _check_project_access(name, user, db, "viewer")
    ai_dir = get_ai_workflow_dir(name)

    proj = (await db.execute(select(Project).where(Project.slug == name))).scalar_one_or_none()
    backlog = []
    if proj:
        result = await db.execute(
            select(BacklogItemModel).where(BacklogItemModel.project_id == proj.id)
            .options(selectinload(BacklogItemModel.images))
            .order_by(BacklogItemModel.sort_order, BacklogItemModel.sequence_number)
        )
        for bi in result.scalars().all():
            images = [{"url": f"/api/projects/{name}/backlog/{bi.sequence_number}/images/{img.original_filename}"}
                      for img in (bi.images or [])]
            backlog.append({"id": bi.sequence_number, "task": bi.title, "title": bi.title,
                            "description": bi.description or "", "priority": bi.priority or "medium",
                            "status": bi.status or "todo", "images": images})

    return {
        "name": name,
        "project": read_md(ai_dir / "project.md"),
        "backlog": backlog,
        "pipeline": read_md(ai_dir / "pipeline.md"),
        "pipeline_cards": parse_pipeline(read_md(ai_dir / "pipeline.md")),
    }


# ---------------------------------------------------------------------------
# Backlog (DB-backed)
# ---------------------------------------------------------------------------

async def _resolve_project_and_item(db, name: str, item_id: str):
    """Helper: resolve Project + BacklogItem by slug + sequence_number."""
    from dashboard.db.models.project import Project
    from dashboard.db.models.backlog import BacklogItem as BacklogItemModel
    proj = (await db.execute(select(Project).where(Project.slug == name))).scalar_one_or_none()
    if not proj:
        return None, None
    bi = (await db.execute(
        select(BacklogItemModel).where(
            BacklogItemModel.project_id == proj.id,
            BacklogItemModel.sequence_number == int(item_id),
        )
    )).scalar_one_or_none()
    return proj, bi


@router.get("/api/projects/{name}/backlog/{item_id}")
async def get_backlog_item(name: str, item_id: str, user: User = Depends(get_current_user), db=Depends(get_db)):
    name = _safe_name(name)
    await _check_project_access(name, user, db, "viewer")
    _, bi = await _resolve_project_and_item(db, name, _safe_id(item_id))
    if not bi:
        return JSONResponse({"error": "Item not found"}, status_code=404)
    return {"id": bi.sequence_number, "task": bi.title, "status": bi.status, "priority": bi.priority}


@router.post("/api/projects/{name}/backlog")
async def add_backlog_item(
    name: str,
    task: str = Form(...),
    description: str = Form(""),
    priority: str = Form("medium"),
    images: list[UploadFile] = File(default=[]),
    user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    from dashboard.db.models.project import Project
    from dashboard.db.models.backlog import BacklogItem as BacklogItemModel, BacklogItemImage

    name = _safe_name(name)
    await _check_project_access(name, user, db, "editor")
    proj = (await db.execute(select(Project).where(Project.slug == name))).scalar_one_or_none()
    if not proj:
        return JSONResponse({"error": "Project not found"}, status_code=404)

    proj.task_counter += 1
    new_seq = proj.task_counter
    bi = BacklogItemModel(
        project_id=proj.id,
        sequence_number=new_seq,
        task_id_display=f"{proj.prefix}-{new_seq}",
        title=task,
        description=description,
        priority=priority,
        status="todo",
        sort_order=new_seq,
        created_by=user.id,
    )
    db.add(bi)
    await db.flush()

    for img in images:
        if img.filename:
            data = await img.read()
            from dashboard.storage.manager import storage
            store_info = await storage.save_backlog_image(
                visibility=proj.visibility, project_prefix=proj.prefix,
                project_dir=await resolve_local_path(db, proj), item_seq=new_seq,
                filename=img.filename, data=data,
            )
            db.add(BacklogItemImage(
                backlog_item_id=bi.id, **store_info,
            ))

    await db.commit()
    return {"id": new_seq}


@router.post("/api/projects/{name}/backlog/{item_id}/images")
async def add_images_to_item(
    name: str,
    item_id: str,
    images: list[UploadFile] = File(...),
    user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    from dashboard.db.models.backlog import BacklogItemImage

    name = _safe_name(name)
    await _check_project_access(name, user, db, "editor")
    proj, bi = await _resolve_project_and_item(db, name, _safe_id(item_id))
    if not bi:
        return JSONResponse({"error": "Item not found"}, status_code=404)

    for img in images:
        if img.filename:
            data = await img.read()
            from dashboard.storage.manager import storage
            store_info = await storage.save_backlog_image(
                visibility=proj.visibility, project_prefix=proj.prefix,
                project_dir=await resolve_local_path(db, proj), item_seq=bi.sequence_number,
                filename=img.filename, data=data,
            )
            db.add(BacklogItemImage(
                backlog_item_id=bi.id, **store_info,
            ))

    await db.commit()
    return {"ok": True}


@router.delete("/api/projects/{name}/backlog/{item_id}/images/{filename}")
async def delete_image(
    name: str,
    item_id: str,
    filename: str,
    user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    from dashboard.db.models.backlog import BacklogItemImage

    name = _safe_name(name)
    await _check_project_access(name, user, db, "editor")
    _, bi = await _resolve_project_and_item(db, name, _safe_id(item_id))
    if not bi:
        return JSONResponse({"error": "Item not found"}, status_code=404)

    result = await db.execute(
        select(BacklogItemImage).where(
            BacklogItemImage.backlog_item_id == bi.id,
            BacklogItemImage.original_filename == _safe_id(filename),
        )
    )
    img_record = result.scalar_one_or_none()
    if img_record:
        from dashboard.storage.manager import storage
        await storage.delete_backlog_image(img_record.storage_type, img_record.s3_key, img_record.local_path)
        await db.delete(img_record)
        await db.commit()
    return {"ok": True}


@router.put("/api/projects/{name}/backlog/{item_id}")
async def update_backlog_item(
    name: str,
    item_id: str,
    item: BacklogItem,
    user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    name = _safe_name(name)
    await _check_project_access(name, user, db, "editor")
    _, bi = await _resolve_project_and_item(db, name, _safe_id(item_id))
    if not bi:
        return JSONResponse({"error": "Item not found"}, status_code=404)

    if item.task:
        bi.title = item.task
    if item.description is not None:
        bi.description = item.description
    if item.priority is not None:
        bi.priority = item.priority
    if item.status:
        bi.status = item.status
    await db.commit()
    return {"ok": True}


@router.delete("/api/projects/{name}/backlog/{item_id}")
async def delete_backlog_item(
    name: str,
    item_id: str,
    user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    name = _safe_name(name)
    await _check_project_access(name, user, db, "editor")
    _, bi = await _resolve_project_and_item(db, name, _safe_id(item_id))
    if not bi:
        return JSONResponse({"error": "Item not found"}, status_code=404)
    await db.delete(bi)
    await db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Pipeline (legacy markdown-based)
# ---------------------------------------------------------------------------

@router.put("/api/projects/{name}/pipeline")
async def update_pipeline(
    name: str,
    body: PipelineUpdate,
    user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    name = _safe_name(name)
    await _check_project_access(name, user, db, "editor")
    ai_dir = get_ai_workflow_dir(name)
    write_md(ai_dir / "pipeline.md", body.content)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Project-level agent instructions
# ---------------------------------------------------------------------------

@router.get("/api/projects/{name}/agents")
async def get_project_agents(name: str, user: User = Depends(get_current_user), db=Depends(get_db)):
    """Get agent instructions for a project. Falls back to global (DB) if no project override."""
    from dashboard.db.models.agent_config import AgentConfig
    name = _safe_name(name)
    await _check_project_access(name, user, db, "viewer")
    project = await _resolve_project_db(db, name)

    # Load all global configs
    globals_result = await db.execute(
        select(AgentConfig).where(AgentConfig.project_id == None)
    )
    global_configs = {ac.agent_name: ac.instructions_md for ac in globals_result.scalars().all()}

    # Load project overrides (if project exists in DB)
    project_configs = {}
    if project:
        proj_result = await db.execute(
            select(AgentConfig).where(AgentConfig.project_id == project.id)
        )
        project_configs = {ac.agent_name: ac.instructions_md for ac in proj_result.scalars().all()}

    # Build result: project override > global > empty
    result = {}
    all_agents = set(list(global_configs.keys()) + PIPELINE_AGENTS)
    for agent_name in sorted(all_agents):
        if agent_name in project_configs:
            result[agent_name] = {"content": project_configs[agent_name], "source": "project"}
        elif agent_name in global_configs:
            result[agent_name] = {"content": global_configs[agent_name], "source": "global"}
        else:
            result[agent_name] = {"content": "", "source": "default"}
    return result


@router.put("/api/projects/{name}/agents/{agent}")
async def update_project_agent(
    name: str,
    agent: str,
    body: InstructionsUpdate,
    user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    from dashboard.db.models.agent_config import AgentConfig
    name = _safe_name(name)
    await _check_project_access(name, user, db, "editor")
    agent = _safe_id(agent)
    project = await _resolve_project_db(db, name)
    if not project:
        return JSONResponse({"error": "Project not found in DB"}, status_code=404)

    # Upsert project-level agent config
    existing = await db.execute(
        select(AgentConfig).where(
            AgentConfig.project_id == project.id,
            AgentConfig.agent_name == agent,
        )
    )
    ac = existing.scalar_one_or_none()
    if ac:
        ac.instructions_md = body.content
        ac.is_override = True
    else:
        db.add(AgentConfig(
            project_id=project.id,
            agent_name=agent,
            instructions_md=body.content,
            is_override=True,
        ))
    await db.commit()
    return {"ok": True}


@router.delete("/api/projects/{name}/agents/{agent}")
async def reset_project_agent(
    name: str,
    agent: str,
    user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    """Reset to global instructions (delete project override)."""
    from dashboard.db.models.agent_config import AgentConfig
    name = _safe_name(name)
    await _check_project_access(name, user, db, "editor")
    agent = _safe_id(agent)
    project = await _resolve_project_db(db, name)
    if not project:
        return JSONResponse({"error": "Project not found in DB"}, status_code=404)

    existing = await db.execute(
        select(AgentConfig).where(
            AgentConfig.project_id == project.id,
            AgentConfig.agent_name == agent,
        )
    )
    ac = existing.scalar_one_or_none()
    if ac:
        await db.delete(ac)
        await db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Project pipelines (DB-backed, Visual Builder)
# ---------------------------------------------------------------------------

def _pl_to_dict(pl) -> dict:
    """Convert PipelineDefinition ORM object to API dict."""
    return {
        "id": str(pl.id),
        "name": pl.name,
        "is_default": pl.is_default,
        "graph": pl.graph_json,
        "stages_order": pl.stages_order,
    }


async def _resolve_project_db(db, name: str):
    """Get Project DB record by slug. Returns None if not found."""
    from dashboard.db.models.project import Project
    result = await db.execute(select(Project).where(Project.slug == name))
    return result.scalar_one_or_none()


async def _ensure_default_pipeline(db, project) -> None:
    """No-op — global templates are used directly, not copied."""
    pass


@router.get("/api/projects/{name}/pipelines")
async def list_pipelines(name: str, user: User = Depends(get_current_user), db=Depends(get_db)):
    name = _safe_name(name)
    await _check_project_access(name, user, db, "viewer")
    project = await _resolve_project_db(db, name)
    if not project:
        return []

    # Project-specific pipelines (editable by editor+)
    result = await db.execute(
        select(PipelineDefinition)
        .where(PipelineDefinition.project_id == project.id)
        .order_by(PipelineDefinition.is_default.desc(), PipelineDefinition.name)
    )
    items = []
    for pl in result.scalars().all():
        d = _pl_to_dict(pl)
        d["readonly"] = False
        items.append(d)

    # Global templates (editable for superadmin, read-only for others)
    from dashboard.db.models.pipeline import GlobalPipelineTemplate
    gresult = await db.execute(
        select(GlobalPipelineTemplate).order_by(GlobalPipelineTemplate.is_active.desc(), GlobalPipelineTemplate.name)
    )
    for gt in gresult.scalars().all():
        items.append({
            "id": str(gt.id),
            "name": gt.name,
            "is_default": False,
            "graph": gt.graph_json,
            "stages_order": gt.stages_order,
            "final_task_status": gt.final_task_status,
            "readonly": not user.is_superadmin,
            "is_global": True,
        })

    return items


@router.post("/api/projects/{name}/pipelines")
async def create_pipeline(name: str, body: dict, user: User = Depends(get_current_user), db=Depends(get_db)):
    name = _safe_name(name)
    await _check_project_access(name, user, db, "editor")
    project = await _resolve_project_db(db, name)
    if not project:
        return JSONResponse({"error": "Project not found in DB"}, status_code=404)

    pl = PipelineDefinition(
        project_id=project.id,
        name=body.get("name", "New Pipeline"),
        is_default=False,
        graph_json=body.get("graph", {"drawflow": {"Home": {"data": {}}}}),
        stages_order=body.get("stages_order", []),
    )
    db.add(pl)
    await db.commit()
    await db.refresh(pl)
    return _pl_to_dict(pl)


@router.get("/api/projects/{name}/pipelines/{pl_id}")
async def get_pipeline(name: str, pl_id: str, user: User = Depends(get_current_user), db=Depends(get_db)):
    name = _safe_name(name)
    await _check_project_access(name, user, db, "viewer")
    try:
        pid = uuid.UUID(pl_id)
    except ValueError:
        return JSONResponse({"error": "Invalid pipeline ID"}, status_code=400)
    pl = await db.get(PipelineDefinition, pid)
    if not pl:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return _pl_to_dict(pl)


@router.put("/api/projects/{name}/pipelines/{pl_id}")
async def update_pipeline_graph(
    name: str,
    pl_id: str,
    body: dict,
    user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    name = _safe_name(name)
    await _check_project_access(name, user, db, "editor")
    try:
        pid = uuid.UUID(pl_id)
    except ValueError:
        return JSONResponse({"error": "Invalid pipeline ID"}, status_code=400)
    pl = await db.get(PipelineDefinition, pid)
    if not pl:
        return JSONResponse({"error": "Not found"}, status_code=404)
    if "graph" in body:
        pl.graph_json = body["graph"]
    if "name" in body:
        pl.name = body["name"]
    if "stages_order" in body:
        pl.stages_order = body["stages_order"]
    await db.commit()
    return {"ok": True}


@router.delete("/api/projects/{name}/pipelines/{pl_id}")
async def delete_pipeline(name: str, pl_id: str, user: User = Depends(get_current_user), db=Depends(get_db)):
    name = _safe_name(name)
    await _check_project_access(name, user, db, "editor")
    try:
        pid = uuid.UUID(pl_id)
    except ValueError:
        return JSONResponse({"error": "Invalid pipeline ID"}, status_code=400)
    pl = await db.get(PipelineDefinition, pid)
    if not pl:
        return JSONResponse({"error": "Not found"}, status_code=404)
    if pl.is_default:
        return JSONResponse({"error": "Cannot delete the active pipeline"}, status_code=400)
    await db.delete(pl)
    await db.commit()
    return {"ok": True}


@router.put("/api/projects/{name}/pipelines/{pl_id}/activate")
async def activate_pipeline(name: str, pl_id: str, user: User = Depends(get_current_user), db=Depends(get_db)):
    """Set this pipeline as the active (default) one for the project."""
    name = _safe_name(name)
    await _check_project_access(name, user, db, "editor")
    project = await _resolve_project_db(db, name)
    if not project:
        return JSONResponse({"error": "Project not found"}, status_code=404)
    try:
        pid = uuid.UUID(pl_id)
    except ValueError:
        return JSONResponse({"error": "Invalid pipeline ID"}, status_code=400)

    # Deactivate all, activate the selected one
    result = await db.execute(
        select(PipelineDefinition).where(PipelineDefinition.project_id == project.id)
    )
    for pl in result.scalars().all():
        pl.is_default = (pl.id == pid)
    await db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Pipeline config (legacy compatibility)
# ---------------------------------------------------------------------------

@router.get("/api/projects/{name}/pipeline-config")
async def get_pipeline_config(name: str, user: User = Depends(get_current_user), db=Depends(get_db)):
    name = _safe_name(name)
    await _check_project_access(name, user, db, "viewer")
    p = PROJECTS / name / "pipeline-config.json"
    if p.exists():
        cfg = json.loads(p.read_text(encoding="utf-8"))
        # migrate old format: list of strings -> list of objects
        if cfg.get("discovery_stages") and isinstance(cfg["discovery_stages"][0], str):
            cfg["discovery_stages"] = [
                {"name": s, "agent": f"discovery-{s}", "description": ""}
                for s in cfg["discovery_stages"]
            ]
        return cfg
    return {
        "stages": ["PM", "PM_REVIEW", "BA", "BA_REVIEW", "DESIGN",
                    "DEV", "DEV_REVIEW", "QA", "QA_REVIEW", "PERF", "COMMIT"],
        "discovery_stages": [
            {"name": "interview", "agent": "discovery-interview",
             "description": "Задать уточняющие вопросы по проекту"},
            {"name": "analysis", "agent": "discovery-analysis",
             "description": "Определить стек и архитектуру"},
            {"name": "decomposition", "agent": "discovery-decomposition",
             "description": "Декомпозировать на задачи"},
            {"name": "confirmation", "agent": "discovery-confirmation",
             "description": "Показать результат и получить подтверждение"},
        ],
    }


@router.put("/api/projects/{name}/pipeline-config")
async def update_pipeline_config(
    name: str,
    body: dict,
    user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    name = _safe_name(name)
    await _check_project_access(name, user, db, "editor")
    p = PROJECTS / name / "pipeline-config.json"
    p.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Global Pipeline Templates (superadmin only)
# ---------------------------------------------------------------------------

@router.get("/api/pipeline-templates")
async def list_templates(user: User = Depends(get_current_user), db=Depends(get_db)):
    from dashboard.db.models.pipeline import GlobalPipelineTemplate
    result = await db.execute(
        select(GlobalPipelineTemplate).order_by(GlobalPipelineTemplate.is_active.desc(), GlobalPipelineTemplate.name)
    )
    return [{
        "id": str(t.id), "name": t.name, "is_active": t.is_active,
        "graph": t.graph_json, "stages_order": t.stages_order,
        "final_task_status": t.final_task_status,
    } for t in result.scalars().all()]


@router.post("/api/pipeline-templates")
async def create_template(body: dict, user: User = Depends(get_current_user), db=Depends(get_db)):
    from dashboard.db.models.pipeline import GlobalPipelineTemplate
    if not user.is_superadmin:
        return JSONResponse({"error": "Superadmin only"}, status_code=403)
    tmpl = GlobalPipelineTemplate(
        name=body.get("name", "New Template"),
        is_active=body.get("is_active", False),
        graph_json=body.get("graph", {"drawflow": {"Home": {"data": {}}}}),
        stages_order=body.get("stages_order", []),
        discovery_stages=body.get("discovery_stages"),
        created_by=user.id,
    )
    # If setting as active, deactivate others
    if tmpl.is_active:
        existing = await db.execute(select(GlobalPipelineTemplate).where(GlobalPipelineTemplate.is_active == True))
        for old in existing.scalars().all():
            old.is_active = False
    db.add(tmpl)
    await db.commit()
    await db.refresh(tmpl)
    return {"id": str(tmpl.id), "name": tmpl.name, "is_active": tmpl.is_active}


@router.put("/api/pipeline-templates/{tmpl_id}")
async def update_template(tmpl_id: str, body: dict, user: User = Depends(get_current_user), db=Depends(get_db)):
    from dashboard.db.models.pipeline import GlobalPipelineTemplate
    if not user.is_superadmin:
        return JSONResponse({"error": "Superadmin only"}, status_code=403)
    tmpl = await db.get(GlobalPipelineTemplate, uuid.UUID(tmpl_id))
    if not tmpl:
        return JSONResponse({"error": "Not found"}, status_code=404)
    if "name" in body: tmpl.name = body["name"]
    if "graph" in body: tmpl.graph_json = body["graph"]
    if "stages_order" in body: tmpl.stages_order = body["stages_order"]
    if "discovery_stages" in body: tmpl.discovery_stages = body["discovery_stages"]
    if "final_task_status" in body: tmpl.final_task_status = body["final_task_status"]
    if body.get("is_active"):
        existing = await db.execute(select(GlobalPipelineTemplate).where(
            GlobalPipelineTemplate.is_active == True, GlobalPipelineTemplate.id != tmpl.id
        ))
        for old in existing.scalars().all():
            old.is_active = False
        tmpl.is_active = True
    await db.commit()
    return {"ok": True}


@router.delete("/api/pipeline-templates/{tmpl_id}")
async def delete_template(tmpl_id: str, user: User = Depends(get_current_user), db=Depends(get_db)):
    from dashboard.db.models.pipeline import GlobalPipelineTemplate
    if not user.is_superadmin:
        return JSONResponse({"error": "Superadmin only"}, status_code=403)
    tmpl = await db.get(GlobalPipelineTemplate, uuid.UUID(tmpl_id))
    if not tmpl:
        return JSONResponse({"error": "Not found"}, status_code=404)
    await db.delete(tmpl)
    await db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Artifacts (per task)
# ---------------------------------------------------------------------------

@router.get("/api/projects/{name}/artifacts")
async def list_task_artifacts(name: str, user: User = Depends(get_current_user), db=Depends(get_db)):
    name = _safe_name(name)
    await _check_project_access(name, user, db, "viewer")
    ai_dir = get_ai_workflow_dir(name)
    arts_dir = ai_dir / "artifacts"
    if not arts_dir.exists():
        return []
    tasks: list[dict] = []
    for d in sorted(arts_dir.iterdir(), key=lambda x: x.name):
        if d.is_dir():
            files: list[dict] = []
            for f in sorted(d.iterdir()):
                if f.is_file() and f.name != "changes.json":
                    files.append({"name": f.name, "type": "doc"})
            # Check for code changes
            cj = d / "code-changes" / "changes.json"
            if cj.exists():
                code = json.loads(cj.read_text(encoding="utf-8"))
                files.append({"name": "code-changes", "type": "code",
                              "files": code.get("files", [])})
            tasks.append({"taskId": d.name, "artifacts": files})
    return tasks


@router.get("/api/projects/{name}/artifacts/{task_id}/code-changes")
async def get_code_changes(
    name: str,
    task_id: str,
    user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    name = _safe_name(name)
    await _check_project_access(name, user, db, "viewer")
    task_id = _safe_id(task_id)
    ai_dir = get_ai_workflow_dir(name)
    f = ai_dir / "artifacts" / task_id / "code-changes" / "changes.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return {"files": []}


@router.get("/api/projects/{name}/artifacts/{task_id}/{filename}")
async def get_task_artifact(
    name: str,
    task_id: str,
    filename: str,
    user: User = Depends(get_current_user),
    db=Depends(get_db),
):
    name = _safe_name(name)
    await _check_project_access(name, user, db, "viewer")
    task_id = _safe_id(task_id)
    filename = _safe_id(filename)
    ai_dir = get_ai_workflow_dir(name)
    f = (ai_dir / "artifacts" / task_id / filename).resolve()
    base = (ai_dir / "artifacts").resolve()
    if not str(f).startswith(str(base)):
        return JSONResponse({"error": "invalid path"}, status_code=400)
    if f.exists():
        return {"content": f.read_text(encoding="utf-8")}
    return {"content": ""}


# ---------------------------------------------------------------------------
# Deploy (merge develop -> master + tag)
# ---------------------------------------------------------------------------

@router.get("/api/projects/{name}/deploy-info")
async def deploy_info(name: str, user: User = Depends(get_current_user), db=Depends(get_db)):
    name = _safe_name(name)
    await _check_project_access(name, user, db, "viewer")
    project_md = read_md(PROJECTS / name / "project.md")
    m = re.search(r'Путь к проекту\s*\n`([^`]+)`', project_md)
    if not m:
        return {"error": "Путь к проекту не найден в project.md"}
    repo = m.group(1)

    def git(args):
        r = subprocess.run(["git"] + args, cwd=repo, capture_output=True, text=True)
        return r.stdout.strip()

    last_tag = git(["tag", "--sort=-v:refname"]).split("\n")[0]
    log = git(["log", f"{last_tag}..develop", "--oneline"])
    return {
        "repo": repo,
        "last_tag": last_tag,
        "commits": log.split("\n") if log else [],
        "branch": git(["branch", "--show-current"]),
    }


@router.post("/api/projects/{name}/deploy")
async def deploy(name: str, body: DeployRequest, user: User = Depends(get_current_user), db=Depends(get_db)):
    name = _safe_name(name)
    await _check_project_access(name, user, db, "owner")
    project_md = read_md(PROJECTS / name / "project.md")
    m = re.search(r'Путь к проекту\s*\n`([^`]+)`', project_md)
    if not m:
        return {"error": "Путь к проекту не найден в project.md"}
    repo = m.group(1)

    def git(args):
        r = subprocess.run(["git"] + args, cwd=repo, capture_output=True, text=True)
        if r.returncode != 0:
            raise Exception(r.stderr.strip() or r.stdout.strip())
        return r.stdout.strip()

    last_tag = git(["tag", "--sort=-v:refname"]).split("\n")[0]
    parts = last_tag.lstrip("v").split(".")
    major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
    if body.bump == "major":
        major, minor, patch = major + 1, 0, 0
    elif body.bump == "minor":
        minor, patch = minor + 1, 0
    else:
        patch += 1
    new_tag = f"v{major}.{minor}.{patch}"

    git(["checkout", "master"])
    git(["merge", "develop", "-m", f"Release {new_tag}: merge develop \u2192 master"])
    git(["tag", "-a", new_tag, "-m", f"Release {new_tag}"])
    git(["push", "origin", "master"])
    git(["push", "origin", new_tag])
    git(["checkout", "develop"])

    return {"ok": True, "tag": new_tag, "prev_tag": last_tag}
