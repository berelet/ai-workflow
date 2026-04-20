import logging
import os
import secrets
import socket
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

logger = logging.getLogger("setup")
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from dashboard.auth.utils import hash_password_async
from dashboard.db.engine import get_db
from dashboard.db.models import (
    User, AgentConfig, Skill, SystemConfig, DashboardInstance,
)
from dashboard.db.models.pipeline import GlobalPipelineTemplate

router = APIRouter(prefix="/api/setup", tags=["setup"])

BASE = Path(__file__).parent.parent.parent  # /var/www/ai-workflow

AGENT_DIRS = [
    "orchestrator", "project-manager", "business-analyst", "designer",
    "developer", "tester", "performance-reviewer",
    "discovery-interview", "discovery-analysis",
    "discovery-decomposition", "discovery-confirmation",
    "architect",
]

PIPELINE_TEMPLATES = [
    {
        "name": "Full Cycle",
        "final_task_status": "done",
        "stages": [
            ("PM", "agent"), ("PM_REVIEW", "reviewer"),
            ("BA", "agent"), ("BA_REVIEW", "reviewer"),
            ("DESIGN", "agent"),
            ("DEV", "agent"), ("DEV_REVIEW", "reviewer"),
            ("QA", "agent"), ("QA_REVIEW", "reviewer"),
            ("PERF", "agent"),
            ("COMMIT", "agent"),
        ],
    },
    {
        "name": "BA Analysis",
        "final_task_status": "todo",
        "stages": [
            ("PM", "agent"), ("PM_REVIEW", "reviewer"),
            ("BA", "agent"), ("BA_REVIEW", "reviewer"),
        ],
    },
    {
        "name": "Architect",
        "final_task_status": "todo",
        "stages": [
            ("PM", "agent"), ("PM_REVIEW", "reviewer"),
            ("BA", "agent"), ("BA_REVIEW", "reviewer"),
            ("ARCH", "agent"), ("ARCH_REVIEW", "reviewer"),
        ],
    },
    {
        "name": "Code Development",
        "final_task_status": "done",
        "stages": [
            ("DEV", "agent"), ("DEV_REVIEW", "reviewer"),
            ("QA", "agent"), ("QA_REVIEW", "reviewer"),
            ("PERF", "agent"),
            ("COMMIT", "agent"),
        ],
    },
]


def _build_linear_graph(stages: list[tuple[str, str]]) -> dict:
    """Build a Drawflow JSON graph from a list of (agent_name, node_type) tuples."""
    nodes = {}
    for i, (agent, ntype) in enumerate(stages):
        node_id = str(i + 1)
        node = {
            "id": i + 1,
            "name": "agent",
            "data": {"agent": agent, "type": ntype},
            "class": "agent-node",
            "html": f'<div class="box"><span>{agent}</span><span class="node-type-badge">{ntype.title()}</span></div>',
            "pos_x": 100 + i * 250,
            "pos_y": 200,
            "inputs": {},
            "outputs": {},
            "typenode": False,
        }
        if i > 0:
            node["inputs"] = {"input_1": {"connections": [{"node": str(i), "input": "output_1"}]}}
        if i < len(stages) - 1:
            node["outputs"] = {"output_1": {"connections": [{"node": str(i + 2), "output": "input_1"}]}}
        nodes[node_id] = node
    return {"drawflow": {"Home": {"data": nodes}}}

DEFAULT_SKILLS = {
    "global": [
        ("Security", "cisco/software-security", "cisco/software-security/SKILL.md"),
        ("Systematic Debugging", "secondsky/claude-skills", "secondsky/claude-skills/plugins/systematic-debugging/skills/systematic-debugging/SKILL.md"),
    ],
    "pm_review": [
        ("Product Manager Toolkit", "alirezarezvani/claude-skills", "alirezarezvani/claude-skills/product-team/product-manager-toolkit/SKILL.md"),
    ],
    "ba_review": [
        ("Requirements Clarity", "softaworks/agent-toolkit", "softaworks/agent-toolkit/skills/requirements-clarity/SKILL.md"),
    ],
    "dev_review": [
        ("FastAPI Python", "mindrally/skills", "mindrally/skills/fastapi-python/SKILL.md"),
        ("React Dev", "softaworks/agent-toolkit", "softaworks/agent-toolkit/skills/react-dev/SKILL.md"),
        ("Software Security", "cisco/software-security", "cisco/software-security/SKILL.md"),
        ("API Testing", "secondsky/claude-skills", "secondsky/claude-skills/plugins/api-testing/skills/api-testing/SKILL.md"),
    ],
    "qa_review": [
        ("Webapp Testing", "anthropics/skills", "anthropics/skills/skills/webapp-testing/SKILL.md"),
    ],
    "perf": [
        ("Web Performance Audit", "secondsky/claude-skills", "secondsky/claude-skills/plugins/web-performance-audit/skills/web-performance-audit/SKILL.md"),
        ("App Performance", "sickn33/antigravity-awesome-skills", "sickn33/antigravity-awesome-skills/skills/application-performance-performance-optimization/SKILL.md"),
        ("Performance Profiling", "sickn33/antigravity-awesome-skills", "sickn33/antigravity-awesome-skills/skills/performance-profiling/SKILL.md"),
    ],
}


# --- Schemas ---

class CreateSuperadminRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=100)


class ConfigureWorkspaceRequest(BaseModel):
    path: str = Field(min_length=1, max_length=500)


# --- Helpers ---

def _env_path() -> Path:
    return BASE / ".env"


def _read_env() -> dict[str, str]:
    """Read .env file as key=value dict."""
    env = {}
    p = _env_path()
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


def _write_env(updates: dict[str, str]) -> None:
    """Update .env file, preserving existing entries and adding new ones."""
    p = _env_path()
    lines = []
    existing_keys = set()

    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                key = stripped.partition("=")[0].strip()
                if key in updates:
                    lines.append(f"{key}={updates[key]}")
                    existing_keys.add(key)
                else:
                    lines.append(line)
            else:
                lines.append(line)

    for key, value in updates.items():
        if key not in existing_keys:
            lines.append(f"{key}={value}")

    p.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def _has_superadmin(db: AsyncSession) -> bool:
    result = await db.execute(select(User).where(User.is_superadmin == True).limit(1))
    return result.scalar_one_or_none() is not None


async def _has_workspaces_dir(db: AsyncSession) -> bool:
    result = await db.execute(
        select(SystemConfig).where(SystemConfig.key == "workspaces_dir")
    )
    return result.scalar_one_or_none() is not None


async def _is_seeded(db: AsyncSession) -> bool:
    result = await db.execute(
        select(SystemConfig).where(SystemConfig.key == "setup_completed")
    )
    cfg = result.scalar_one_or_none()
    return cfg is not None and cfg.value == "true"


async def _tables_exist(db: AsyncSession) -> bool:
    result = await db.execute(
        text("SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name = 'users')")
    )
    return result.scalar()


# --- Routes ---

@router.get("/status")
async def setup_status(db: AsyncSession = Depends(get_db)):
    """Check setup progress. No auth required. Returns minimal info post-setup."""
    try:
        tables_ok = await _tables_exist(db)
    except Exception:
        return {"required": True, "step": "db_error"}

    if not tables_ok:
        return {"required": True, "step": "run_migrations"}

    # If fully seeded, return minimal response (don't leak internal state)
    seeded = await _is_seeded(db)
    if seeded:
        return {"required": False}

    has_admin = await _has_superadmin(db)
    if not has_admin:
        return {"required": True, "step": "create_superadmin"}

    if not await _has_workspaces_dir(db):
        return {
            "required": True,
            "step": "configure_workspace",
            "default_path": str(BASE / "workspaces"),
        }

    return {"required": True, "step": "seed_defaults"}


@router.post("/create-superadmin")
async def create_superadmin(body: CreateSuperadminRequest, db: AsyncSession = Depends(get_db)):
    """Create the first superadmin. Only works when no superadmin exists.
    Uses advisory lock to prevent race conditions."""
    # Prevent post-setup access
    if await _is_seeded(db):
        raise HTTPException(status_code=403, detail="Setup already completed")

    # Advisory lock (key=1) prevents concurrent superadmin creation
    await db.execute(text("SELECT pg_advisory_xact_lock(1)"))

    if await _has_superadmin(db):
        raise HTTPException(status_code=409, detail="Superadmin already exists")

    password_hash = await hash_password_async(body.password)

    # Generate secrets BEFORE any DB writes
    jwt_secret = secrets.token_hex(32)
    dashboard_uuid = str(uuid.uuid4())

    # Prepare all DB objects
    user = User(
        email=body.email.lower(),
        password_hash=password_hash,
        display_name=body.display_name,
        is_superadmin=True,
    )
    inst = DashboardInstance(
        id=uuid.UUID(dashboard_uuid),
        hostname=socket.gethostname(),
    )

    # Write .env BEFORE DB commit — if this fails, no DB changes are made
    try:
        _write_env({
            "JWT_SECRET_KEY": jwt_secret,
            "DASHBOARD_UUID": dashboard_uuid,
        })
    except Exception as e:
        logger.error("Failed to write .env: %s", e)
        raise HTTPException(status_code=500, detail=f"Cannot write secrets to .env: {e}")

    # Single atomic DB commit — both user and dashboard instance
    db.add(user)
    db.add(inst)
    try:
        await db.commit()
    except Exception as e:
        logger.error("DB commit failed during superadmin creation: %s", e)
        raise HTTPException(status_code=500, detail="Database error during setup")

    await db.refresh(user)
    logger.info("Superadmin created: %s (%s)", user.email, user.id)

    # Update runtime AFTER successful commit
    os.environ["JWT_SECRET_KEY"] = jwt_secret
    os.environ["DASHBOARD_UUID"] = dashboard_uuid

    import dashboard.auth.jwt as jwt_mod
    jwt_mod.SECRET_KEY = jwt_secret
    jwt_mod.SETUP_MODE = False
    logger.info("JWT_SECRET_KEY generated, SETUP_MODE disabled, dashboard UUID: %s", dashboard_uuid)

    return {
        "ok": True,
        "user_id": str(user.id),
        "message": "Superadmin created, secrets generated",
    }


@router.post("/configure-workspace")
async def configure_workspace(body: ConfigureWorkspaceRequest, db: AsyncSession = Depends(get_db)):
    """Configure the workspace directory where new projects will be cloned.
    Validates the path is creatable, writable, and not a file."""
    if await _is_seeded(db):
        raise HTTPException(status_code=403, detail="Setup already completed")
    if not await _has_superadmin(db):
        raise HTTPException(status_code=403, detail="Unauthorized")

    path_str = body.path.strip()
    p = Path(path_str).resolve()

    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise HTTPException(status_code=400, detail=f"Cannot create directory: {e}")

    if not p.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")
    if not os.access(p, os.W_OK):
        raise HTTPException(status_code=400, detail="Directory is not writable")

    existing = (await db.execute(
        select(SystemConfig).where(SystemConfig.key == "workspaces_dir")
    )).scalar_one_or_none()
    if existing:
        existing.value = str(p)
    else:
        db.add(SystemConfig(key="workspaces_dir", value=str(p)))

    await db.commit()
    logger.info("Workspaces directory configured: %s", p)
    return {"ok": True, "path": str(p)}


@router.post("/seed-defaults")
async def seed_defaults(db: AsyncSession = Depends(get_db)):
    """Seed default agent configs, skills, and mark setup complete. Runs once.
    Guarded: rejects if setup already completed OR no superadmin exists."""
    if await _is_seeded(db):
        raise HTTPException(status_code=403, detail="Setup already completed")
    if not await _has_superadmin(db):
        raise HTTPException(status_code=403, detail="Unauthorized")

    # Advisory lock prevents concurrent seed calls
    await db.execute(text("SELECT pg_advisory_xact_lock(2)"))

    # 1. Seed global agent configs from instructions.md files
    seeded_agents = 0
    for agent_dir in AGENT_DIRS:
        instructions_path = BASE / agent_dir / "instructions.md"
        if instructions_path.exists():
            content = instructions_path.read_text(encoding="utf-8")
            existing = await db.execute(
                select(AgentConfig).where(
                    AgentConfig.project_id == None,
                    AgentConfig.agent_name == agent_dir,
                )
            )
            if not existing.scalar_one_or_none():
                db.add(AgentConfig(
                    agent_name=agent_dir,
                    instructions_md=content,
                    is_override=False,
                ))
                seeded_agents += 1

    # 2. Seed skills registry
    tessl_tiles = BASE / ".tessl" / "tiles"
    seeded_skills = 0
    for scope, skill_list in DEFAULT_SKILLS.items():
        for name, source, skill_path in skill_list:
            existing = await db.execute(
                select(Skill).where(Skill.skill_path == skill_path)
            )
            if existing.scalar_one_or_none():
                continue

            # Try to read skill content
            full_path = tessl_tiles / skill_path
            content = None
            if full_path.exists():
                content = full_path.read_text(encoding="utf-8")

            db.add(Skill(
                name=name,
                source=source,
                skill_path=skill_path,
                agent_scope=scope,
                content_md=content,
                is_installed=full_path.exists(),
            ))
            seeded_skills += 1

    # 3. Seed global pipeline templates
    admin = (await db.execute(
        select(User).where(User.is_superadmin == True).limit(1)
    )).scalar_one()
    seeded_pipelines = 0
    for tmpl in PIPELINE_TEMPLATES:
        existing = await db.execute(
            select(GlobalPipelineTemplate).where(
                GlobalPipelineTemplate.name == tmpl["name"]
            )
        )
        if existing.scalar_one_or_none():
            continue
        graph = _build_linear_graph(tmpl["stages"])
        stages_order = [s[0] for s in tmpl["stages"]]
        db.add(GlobalPipelineTemplate(
            name=tmpl["name"],
            graph_json=graph,
            stages_order=stages_order,
            final_task_status=tmpl["final_task_status"],
            created_by=admin.id,
        ))
        seeded_pipelines += 1

    # 4. Mark setup as complete
    db.add(SystemConfig(key="setup_completed", value="true"))
    db.add(SystemConfig(key="schema_version", value="004"))

    await db.commit()
    logger.info("Setup seed complete: %d agents, %d skills, %d pipelines",
                seeded_agents, seeded_skills, seeded_pipelines)

    return {
        "ok": True,
        "agents_seeded": seeded_agents,
        "skills_seeded": seeded_skills,
        "pipelines_seeded": seeded_pipelines,
    }
