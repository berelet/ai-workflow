"""Git operation endpoints: test connection, clone-from-git with SSE progress.

These endpoints support the "Create project from git URL" flow:
- POST /api/git/test-connection — validates SSH key + repo URL, returns default branch
- POST /api/projects/clone-stream — SSE stream of git clone progress, creates project on success
"""
import asyncio
import json
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Literal

from dashboard.auth.crypto import decrypt_ssh_key
from dashboard.auth.middleware import get_current_user
from dashboard.auth.utils import parse_uuid
from dashboard.db.engine import get_db, async_session as async_session_factory
from dashboard.db.models.project import Project, ProjectMembership
from dashboard.db.models.ssh_key import SSHKey
from dashboard.db.models.system_config import SystemConfig
from dashboard.db.models.user import User
from dashboard.helpers import BASE, PROJECTS, write_md, safe_path_param
from dashboard.services.git_manager import _SSHKeyContext, _run_git

logger = logging.getLogger("routers.git_ops")

router = APIRouter(tags=["git_ops"])


# ── Validation helpers ──────────────────────────────────────────────────

# Reject any URL containing shell metacharacters that could break out of git
_DANGEROUS_URL_CHARS = set(';|&`$()<>\'"\n\r\t\\')


def _is_safe_git_url(url: str) -> bool:
    """Validate a git URL: no shell metacharacters, recognizable scheme."""
    if not url or len(url) > 500:
        return False
    if any(c in _DANGEROUS_URL_CHARS for c in url):
        return False
    # Must look like ssh://, git://, https://, or git@host:path
    return bool(re.match(r'^([\w\-+]+://[\w.\-]+|[\w\-]+@[\w.\-]+:)', url))


def _classify_git_error(stderr: str, stdout: str = "") -> tuple[str, str]:
    """Map git error output to (error_code, human_message).

    Order matters: more specific phrases must be checked before generic ones,
    because git's "Could not read from remote repository" is appended to many
    different upstream failures (auth, host key, missing repo).
    """
    combined = (stderr + " " + stdout).lower()
    # Most specific first
    if "host key verification failed" in combined:
        return ("host_key", "Host key verification failed.")
    if "repository not found" in combined or "does not exist" in combined:
        return ("not_found", "Repository not found. Check the URL and your access rights.")
    if "connection refused" in combined or "could not resolve" in combined or "name or service not known" in combined:
        return ("network", "Cannot reach git host. Check network and URL.")
    # Generic auth failures last (the "could not read from remote" trailer appears with everything above too)
    if "permission denied" in combined or "publickey" in combined or "could not read from remote" in combined:
        return ("permission_denied", "SSH key not authorized. Add the public key to your git provider.")
    return ("git_failed", stderr.strip()[:300] or "Git operation failed")


def _extract_default_branch(ls_remote_output: str) -> str:
    """Parse 'ref: refs/heads/main\\tHEAD' lines to find default branch."""
    for line in ls_remote_output.splitlines():
        if line.startswith("ref:"):
            parts = line.split()
            if len(parts) >= 2 and parts[1].startswith("refs/heads/"):
                return parts[1][len("refs/heads/"):]
    return "main"


async def _get_workspaces_dir(db: AsyncSession) -> Path:
    """Read workspaces_dir from SystemConfig. Falls back to env var, then default.

    Default lives inside the ai-workflow project root (`BASE/workspaces/`) so
    the dashboard process always has write access to it without needing sudo.
    The folder is gitignored.
    """
    result = await db.execute(
        select(SystemConfig).where(SystemConfig.key == "workspaces_dir")
    )
    cfg = result.scalar_one_or_none()
    if cfg and cfg.value:
        return Path(cfg.value)
    env_val = os.environ.get("WORKSPACES_DIR")
    if env_val:
        return Path(env_val)
    return BASE / "workspaces"


async def _resolve_user_ssh_key(db: AsyncSession, user: User, ssh_key_id: str) -> SSHKey:
    """Look up an SSH key that belongs to the current user. Raises HTTPException if missing."""
    kid = parse_uuid(ssh_key_id, "ssh_key_id")
    result = await db.execute(
        select(SSHKey).where(SSHKey.id == kid, SSHKey.user_id == user.id)
    )
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=404, detail="SSH key not found")
    return key


# ── Schemas ─────────────────────────────────────────────────────────────

class TestConnectionRequest(BaseModel):
    url: str = Field(min_length=1, max_length=500)
    ssh_key_id: str


class CloneProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    stack: str = ""
    visibility: Literal["public", "private"] = "public"
    repo_url: str = Field(min_length=1, max_length=500)
    ssh_key_id: str


class BindCloneRequest(BaseModel):
    repo_url: str = Field(min_length=1, max_length=500)
    ssh_key_id: str


# ── Endpoints ───────────────────────────────────────────────────────────

@router.post("/api/git/test-connection")
async def test_connection(
    body: TestConnectionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Test that the SSH key can reach the repo and discover the default branch.

    Runs `git ls-remote --symref <url> HEAD` — fast (1-2s), no checkout.
    Returns default branch on success, classified error on failure.
    """
    url = body.url.strip()
    if not _is_safe_git_url(url):
        return {"ok": False, "error": "invalid_url", "message": "Invalid git URL format"}

    key = await _resolve_user_ssh_key(db, user, body.ssh_key_id)

    with _SSHKeyContext(key.encrypted_private_key) as env:
        rc, stdout, stderr = await _run_git(
            ["ls-remote", "--symref", url, "HEAD"],
            cwd="/tmp", env=env,
        )

    if rc != 0:
        code, msg = _classify_git_error(stderr, stdout)
        return {"ok": False, "error": code, "message": msg}

    default_branch = _extract_default_branch(stdout)
    return {"ok": True, "default_branch": default_branch}


# ── SSE clone helpers ───────────────────────────────────────────────────

def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


async def _clone_with_progress(
    url: str,
    dest: str,
    encrypted_key: str,
):
    """Async generator yielding SSE events for git clone --progress.

    Yields dicts: {type: 'progress', line: '...'} or {type: 'error', message: '...'}
    or {type: 'done'}.
    """
    # Manually manage the SSH key tempfile so it lives across yield points.
    # _SSHKeyContext uses 'with' which would close immediately if used naively here.
    key_content = decrypt_ssh_key(encrypted_key)
    fd, key_path = tempfile.mkstemp(suffix=".key")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(key_content)
        os.chmod(key_path, 0o600)
        env = os.environ.copy()
        env["GIT_SSH_COMMAND"] = f"ssh -i {key_path} -o StrictHostKeyChecking=no"
        env["GIT_TERMINAL_PROMPT"] = "0"

        proc = await asyncio.create_subprocess_exec(
            "git", "clone", "--progress", url, dest,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        # git clone writes progress to stderr; merge stdout too just in case
        async def _drain(stream, tag):
            async for raw in stream:
                line = raw.decode("utf-8", errors="replace").rstrip()
                if line:
                    yield {"type": "progress", "stream": tag, "line": line}

        # Multiplex stderr (primary) — clone progress comes here
        captured_stderr = []
        captured_stdout = []
        async for evt in _drain(proc.stderr, "stderr"):
            captured_stderr.append(evt["line"])
            yield evt
        # Drain stdout in case anything was written there too
        remaining = await proc.stdout.read()
        if remaining:
            for line in remaining.decode("utf-8", errors="replace").splitlines():
                if line.strip():
                    captured_stdout.append(line)
                    yield {"type": "progress", "stream": "stdout", "line": line}

        await proc.wait()
        if proc.returncode == 0:
            yield {"type": "done"}
        else:
            code, msg = _classify_git_error("\n".join(captured_stderr), "\n".join(captured_stdout))
            yield {"type": "error", "code": code, "message": msg}
    finally:
        if os.path.exists(key_path):
            os.unlink(key_path)


@router.post("/api/projects/clone-stream")
async def clone_stream(
    body: CloneProjectRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Stream git clone progress via SSE, then create the project record on success.

    On any failure (validation, clone, post-clone), the partial workspace folder is removed.
    """
    # ── Pre-validate everything before opening the stream ──
    url = body.repo_url.strip()
    if not _is_safe_git_url(url):
        raise HTTPException(status_code=400, detail="Invalid git URL format")

    # Compute slug
    slug = re.sub(r'[^a-z0-9\-]', '-', body.name.lower()).strip('-')
    slug = re.sub(r'-+', '-', slug)
    if not slug:
        raise HTTPException(status_code=400, detail="Invalid project name")
    slug = safe_path_param(slug)

    # Slug uniqueness — check both DB and PROJECTS dir
    if (PROJECTS / slug).exists():
        raise HTTPException(status_code=409, detail="Проект уже существует")
    existing = (await db.execute(
        select(Project).where(Project.slug == slug)
    )).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Проект уже существует")

    # SSH key
    key = await _resolve_user_ssh_key(db, user, body.ssh_key_id)
    encrypted_key = key.encrypted_private_key

    # Workspaces dir must exist
    workspaces_dir = await _get_workspaces_dir(db)
    if not workspaces_dir.is_dir():
        try:
            workspaces_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"Workspaces dir not available: {e}")

    dest = workspaces_dir / slug
    if dest.exists():
        raise HTTPException(status_code=409, detail=f"Destination {dest} already exists")

    # Capture user/project metadata for the generator (don't pass DB session)
    user_id = user.id
    user_email = user.email
    project_meta = {
        "slug": slug,
        "name": body.name,
        "description": body.description,
        "stack": body.stack,
        "visibility": body.visibility,
        "repo_url": url,
        "dest": str(dest),
    }

    async def _generator():
        # Send initial event so the client knows we're alive
        yield _sse({"type": "phase", "phase": "starting", "dest": str(dest)})

        clone_ok = False
        try:
            async for evt in _clone_with_progress(url, str(dest), encrypted_key):
                if evt["type"] == "progress":
                    yield _sse(evt)
                elif evt["type"] == "done":
                    clone_ok = True
                elif evt["type"] == "error":
                    yield _sse(evt)
                    return
        except Exception as e:
            logger.exception("Clone subprocess crashed")
            yield _sse({"type": "error", "code": "internal", "message": str(e)})
            return

        if not clone_ok:
            yield _sse({"type": "error", "code": "git_failed", "message": "Clone failed"})
            return

        # ── Post-clone: detect default branch, write .gitignore, create DB records ──
        yield _sse({"type": "phase", "phase": "finalizing"})
        try:
            # Detect actual default branch from cloned repo
            default_branch = "main"
            rc, stdout_b, _ = await _run_git(
                ["symbolic-ref", "--short", "HEAD"], cwd=str(dest)
            )
            if rc == 0 and stdout_b.strip():
                default_branch = stdout_b.strip()

            # Append .ai-workflow/ to .gitignore (locally, no commit)
            gitignore = dest / ".gitignore"
            existing_lines = []
            if gitignore.exists():
                existing_lines = gitignore.read_text("utf-8").splitlines()
            if ".ai-workflow/" not in existing_lines and ".ai-workflow" not in existing_lines:
                with gitignore.open("a", encoding="utf-8") as f:
                    if existing_lines and not existing_lines[-1] == "":
                        f.write("\n")
                    f.write(".ai-workflow/\n")

            # Create .ai-workflow/ inside the cloned repo
            ai_dir = dest / ".ai-workflow"
            ai_dir.mkdir(parents=True, exist_ok=True)
            md = (
                f"# {project_meta['name']}\n\n"
                f"## Описание\n{project_meta['description']}\n\n"
                f"## Стек\n{project_meta['stack']}\n\n"
                f"## Git\n`{project_meta['repo_url']}`\n"
            )
            write_md(ai_dir / "project.md", md)
            write_md(ai_dir / "pipeline.md", "")

            # Create the project registry directory (for legacy compat with PROJECTS / slug layout)
            registry = PROJECTS / project_meta["slug"]
            registry.mkdir(parents=True, exist_ok=True)
            cfg = {
                "stages": [
                    "PM", "PM_REVIEW", "BA", "BA_REVIEW", "DESIGN",
                    "DEV", "DEV_REVIEW", "QA", "QA_REVIEW", "PERF", "COMMIT",
                ],
                "project_dir": str(dest),
            }
            (registry / "pipeline-config.json").write_text(
                json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8",
            )

            # Compute prefix
            alpha_chars = [c for c in project_meta["slug"] if c.isalpha()]
            base_prefix = ("".join(alpha_chars[:4]) or project_meta["slug"][:4]).upper()

            # Open a fresh DB session inside the generator (request-scoped session is gone)
            async with async_session_factory() as fresh_db:
                # Re-check uniqueness inside the new session
                exists = (await fresh_db.execute(
                    select(Project).where(Project.slug == project_meta["slug"])
                )).scalar_one_or_none()
                if exists:
                    yield _sse({"type": "error", "code": "conflict", "message": "Project was created concurrently"})
                    raise RuntimeError("conflict")

                # Resolve unique prefix
                prefix = base_prefix
                counter = 1
                while True:
                    e = (await fresh_db.execute(
                        select(Project).where(Project.prefix == prefix)
                    )).scalar_one_or_none()
                    if not e:
                        break
                    prefix = f"{base_prefix[:3]}{counter}"
                    counter += 1

                db_project = Project(
                    slug=project_meta["slug"],
                    prefix=prefix,
                    name=project_meta["name"],
                    description=project_meta["description"],
                    stack=project_meta["stack"],
                    visibility=project_meta["visibility"],
                    repo_url=project_meta["repo_url"],
                    base_branch=default_branch,
                    created_by=user_id,
                )
                fresh_db.add(db_project)
                await fresh_db.flush()

                fresh_db.add(ProjectMembership(
                    user_id=user_id,
                    project_id=db_project.id,
                    role="owner",
                ))

                # Bind the cloned dest to THIS dashboard instance
                from dashboard.services.instance_paths import set_local_path
                await set_local_path(fresh_db, db_project.id, str(dest))

                # Copy active global pipeline template
                from dashboard.routers.projects import _ensure_default_pipeline
                await _ensure_default_pipeline(fresh_db, db_project)

                await fresh_db.commit()

            yield _sse({
                "type": "done",
                "slug": project_meta["slug"],
                "default_branch": default_branch,
            })
        except RuntimeError:
            # Already sent error event; clean up filesystem and stop
            try:
                if dest.exists():
                    shutil.rmtree(dest)
                reg = PROJECTS / project_meta["slug"]
                if reg.exists():
                    shutil.rmtree(reg)
            except Exception:
                pass
            return
        except Exception as e:
            logger.exception("Post-clone setup failed")
            yield _sse({"type": "error", "code": "post_clone_failed", "message": str(e)})
            try:
                if dest.exists():
                    shutil.rmtree(dest)
                reg = PROJECTS / project_meta["slug"]
                if reg.exists():
                    shutil.rmtree(reg)
            except Exception:
                pass
            return

    return StreamingResponse(
        _generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/api/projects/{slug}/bind-clone-stream")
async def bind_clone_stream(
    slug: str,
    body: BindCloneRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Clone a repo for an EXISTING project and bind it to this dashboard instance.

    Mirrors `clone_stream` but skips creating the project row — the project
    must already exist in the catalog. Used by the "set up local copy" flow
    when a user opens a project that has no on-disk presence on this dashboard.

    Requires ≥ developer role on the project.
    """
    # ── Pre-validate ──
    from dashboard.helpers import safe_path_param
    from dashboard.routers.projects import _check_project_access
    from dashboard.services.instance_paths import (
        get_current_instance_id, set_local_path,
    )
    from dashboard.db.models.dashboard_instance import InstanceProjectBinding
    from dashboard.helpers import write_md

    slug = safe_path_param(slug)
    await _check_project_access(slug, user, db, "developer")

    # Look up project
    proj = (await db.execute(
        select(Project).where(Project.slug == slug)
    )).scalar_one_or_none()
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    # Refuse if already bound on this instance — caller should use the
    # already-bound path instead of clobbering it.
    instance_id = get_current_instance_id()
    if instance_id is not None:
        existing_binding = (await db.execute(
            select(InstanceProjectBinding).where(
                InstanceProjectBinding.instance_id == instance_id,
                InstanceProjectBinding.project_id == proj.id,
            )
        )).scalar_one_or_none()
        if existing_binding:
            raise HTTPException(
                status_code=409,
                detail=f"Project already bound on this instance at {existing_binding.local_path}",
            )

    url = body.repo_url.strip()
    if not _is_safe_git_url(url):
        raise HTTPException(status_code=400, detail="Invalid git URL format")

    # SSH key
    key = await _resolve_user_ssh_key(db, user, body.ssh_key_id)
    encrypted_key = key.encrypted_private_key

    # Workspaces dir
    workspaces_dir = await _get_workspaces_dir(db)
    if not workspaces_dir.is_dir():
        try:
            workspaces_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"Workspaces dir not available: {e}")

    dest = workspaces_dir / slug
    if dest.exists():
        raise HTTPException(status_code=409, detail=f"Destination {dest} already exists")

    project_id = proj.id
    project_name = proj.name
    project_desc = proj.description or ""
    project_stack = proj.stack or ""
    project_meta = {
        "slug": slug,
        "repo_url": url,
        "dest": str(dest),
    }

    async def _generator():
        yield _sse({"type": "phase", "phase": "starting", "dest": str(dest)})

        clone_ok = False
        try:
            async for evt in _clone_with_progress(url, str(dest), encrypted_key):
                if evt["type"] == "progress":
                    yield _sse(evt)
                elif evt["type"] == "done":
                    clone_ok = True
                elif evt["type"] == "error":
                    yield _sse(evt)
                    return
        except Exception as e:
            logger.exception("Bind-clone subprocess crashed")
            yield _sse({"type": "error", "code": "internal", "message": str(e)})
            return

        if not clone_ok:
            yield _sse({"type": "error", "code": "git_failed", "message": "Clone failed"})
            return

        # ── Post-clone: registry, .ai-workflow, binding ──
        yield _sse({"type": "phase", "phase": "finalizing"})
        try:
            # Detect actual default branch
            default_branch = "main"
            rc, stdout_b, _ = await _run_git(
                ["symbolic-ref", "--short", "HEAD"], cwd=str(dest)
            )
            if rc == 0 and stdout_b.strip():
                default_branch = stdout_b.strip()

            # Append .ai-workflow/ to .gitignore (locally, no commit)
            gitignore = dest / ".gitignore"
            existing_lines = []
            if gitignore.exists():
                existing_lines = gitignore.read_text("utf-8").splitlines()
            if ".ai-workflow/" not in existing_lines and ".ai-workflow" not in existing_lines:
                with gitignore.open("a", encoding="utf-8") as f:
                    if existing_lines and not existing_lines[-1] == "":
                        f.write("\n")
                    f.write(".ai-workflow/\n")

            # .ai-workflow inside the cloned repo
            ai_dir = dest / ".ai-workflow"
            ai_dir.mkdir(parents=True, exist_ok=True)
            md = (
                f"# {project_name}\n\n"
                f"## Описание\n{project_desc}\n\n"
                f"## Стек\n{project_stack}\n\n"
                f"## Git\n`{project_meta['repo_url']}`\n"
            )
            write_md(ai_dir / "project.md", md)
            write_md(ai_dir / "pipeline.md", "")

            # Local registry (PROJECTS/<slug>/pipeline-config.json)
            registry = PROJECTS / project_meta["slug"]
            registry.mkdir(parents=True, exist_ok=True)
            cfg = {
                "stages": [
                    "PM", "PM_REVIEW", "BA", "BA_REVIEW", "DESIGN",
                    "DEV", "DEV_REVIEW", "QA", "QA_REVIEW", "PERF", "COMMIT",
                ],
                "project_dir": str(dest),
            }
            (registry / "pipeline-config.json").write_text(
                json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8",
            )

            # Create binding inside a fresh session (request-scoped session is gone in generator)
            async with async_session_factory() as fresh_db:
                await set_local_path(fresh_db, project_id, str(dest))
                await fresh_db.commit()

            yield _sse({
                "type": "done",
                "slug": project_meta["slug"],
                "default_branch": default_branch,
                "local_path": str(dest),
            })
        except Exception as e:
            logger.exception("Bind-clone post-clone setup failed")
            yield _sse({"type": "error", "code": "post_clone_failed", "message": str(e)})
            try:
                if dest.exists():
                    shutil.rmtree(dest)
                reg = PROJECTS / project_meta["slug"]
                if reg.exists():
                    shutil.rmtree(reg)
            except Exception:
                pass
            return

    return StreamingResponse(
        _generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
