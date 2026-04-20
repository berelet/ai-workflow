"""One-time data migration: file-based ai-workflow project → PostgreSQL.

Usage:
    python -m dashboard.db.migrate_filedata

Migrates:
- ai-workflow project as private_db for the first superadmin
- Backlog items from .ai-workflow/backlog.json
- Default pipeline from projects/ai-workflow/pipelines/default.json
- Global agent configs from {agent}/instructions.md
- Skills from .tessl/tiles/ (based on DEFAULT_SKILLS)

Idempotent: checks for existing data before inserting.
"""
import asyncio
import json
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

# Ensure project root is on path
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(str(ROOT / ".env"))

from sqlalchemy import select
from dashboard.db.engine import engine, async_session
from dashboard.db.models import (
    User, Project, ProjectMembership, BacklogItem,
    GlobalPipelineTemplate, PipelineDefinition, AgentConfig, Skill, SystemConfig,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("migrate")

BASE = ROOT
PROJECTS = BASE / "projects"
TESSL_TILES = BASE / ".tessl" / "tiles"

AGENT_DIRS = [
    "orchestrator", "project-manager", "business-analyst", "designer",
    "developer", "tester", "performance-reviewer",
    "discovery-interview", "discovery-analysis",
    "discovery-decomposition", "discovery-confirmation",
    "architect",
]

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


async def migrate():
    async with async_session() as db:
        # 1. Find superadmin
        result = await db.execute(
            select(User).where(User.is_superadmin == True).limit(1)
        )
        superadmin = result.scalar_one_or_none()
        if not superadmin:
            logger.error("No superadmin found. Run setup wizard first.")
            return

        logger.info("Superadmin: %s (%s)", superadmin.email, superadmin.id)

        # 2. Create ai-workflow project (if not exists)
        result = await db.execute(select(Project).where(Project.slug == "ai-workflow"))
        project = result.scalar_one_or_none()

        if not project:
            project = Project(
                slug="ai-workflow",
                prefix="AWF",
                name="AI Workflow",
                description="Multi-agent orchestration system",
                stack="Python 3.12, FastAPI, SQLAlchemy, Vanilla JS",
                visibility="private_db",
                repo_path=str(BASE),
                created_by=superadmin.id,
            )
            db.add(project)
            await db.flush()

            # Add owner membership
            db.add(ProjectMembership(
                user_id=superadmin.id,
                project_id=project.id,
                role="owner",
            ))
            logger.info("Project created: ai-workflow (AWF), private_db")
        else:
            logger.info("Project already exists: ai-workflow")

        # 3. Migrate backlog items
        backlog_path = BASE / ".ai-workflow" / "backlog.json"
        if backlog_path.exists():
            items = json.loads(backlog_path.read_text("utf-8"))
            existing = await db.execute(
                select(BacklogItem).where(BacklogItem.project_id == project.id).limit(1)
            )
            if not existing.scalar_one_or_none():
                for item in items:
                    old_id = item.get("id", 0)
                    title = item.get("task") or item.get("title", f"Task {old_id}")
                    status = item.get("status", "todo")
                    # Map old statuses to new
                    if status not in ("backlog", "todo", "in-progress", "done", "archived"):
                        status = "todo"

                    db.add(BacklogItem(
                        project_id=project.id,
                        sequence_number=old_id,
                        task_id_display=f"AWF-{old_id}",
                        title=title,
                        description=item.get("description", ""),
                        priority=item.get("priority", "medium"),
                        status=status,
                        sort_order=old_id,
                        created_by=superadmin.id,
                    ))

                # Update project task counter
                project.task_counter = max((i.get("id", 0) for i in items), default=0)
                logger.info("Migrated %d backlog items", len(items))
            else:
                logger.info("Backlog items already exist, skipping")

        # 4. Migrate default pipeline
        pipeline_path = PROJECTS / "ai-workflow" / "pipelines" / "default.json"
        if pipeline_path.exists():
            existing = await db.execute(
                select(PipelineDefinition).where(
                    PipelineDefinition.project_id == project.id,
                    PipelineDefinition.is_default == True,
                )
            )
            if not existing.scalar_one_or_none():
                pl_data = json.loads(pipeline_path.read_text("utf-8"))
                config_path = PROJECTS / "ai-workflow" / "pipeline-config.json"
                config = json.loads(config_path.read_text("utf-8")) if config_path.exists() else {}

                db.add(PipelineDefinition(
                    project_id=project.id,
                    name=pl_data.get("name", "Default Pipeline"),
                    is_default=True,
                    graph_json=pl_data.get("graph", {}),
                    stages_order=config.get("stages", []),
                    discovery_stages=config.get("discovery_stages"),
                ))
                logger.info("Migrated default pipeline")
            else:
                logger.info("Default pipeline already exists, skipping")

        # 4b. Create global pipeline template from same data
        existing_tmpl = await db.execute(
            select(GlobalPipelineTemplate).limit(1)
        )
        if not existing_tmpl.scalar_one_or_none():
            config_path = PROJECTS / "ai-workflow" / "pipeline-config.json"
            config = json.loads(config_path.read_text("utf-8")) if config_path.exists() else {}
            pl_path = PROJECTS / "ai-workflow" / "pipelines" / "default.json"
            graph = json.loads(pl_path.read_text("utf-8")).get("graph", {}) if pl_path.exists() else {}

            db.add(GlobalPipelineTemplate(
                name="Default Pipeline",
                is_active=True,
                graph_json=graph,
                stages_order=config.get("stages", ["PM", "PM_REVIEW", "BA", "BA_REVIEW", "DESIGN",
                    "DEV", "DEV_REVIEW", "QA", "QA_REVIEW", "PERF", "COMMIT"]),
                discovery_stages=config.get("discovery_stages"),
                created_by=superadmin.id,
            ))
            logger.info("Created global pipeline template")
        else:
            logger.info("Global pipeline template already exists, skipping")

        # 5. Seed global agent configs (if not already done by setup wizard)
        seeded_agents = 0
        for agent_dir in AGENT_DIRS:
            instructions_path = BASE / agent_dir / "instructions.md"
            if not instructions_path.exists():
                continue
            existing = await db.execute(
                select(AgentConfig).where(
                    AgentConfig.project_id == None,
                    AgentConfig.agent_name == agent_dir,
                )
            )
            if existing.scalar_one_or_none():
                continue
            content = instructions_path.read_text("utf-8")
            db.add(AgentConfig(
                agent_name=agent_dir,
                instructions_md=content,
            ))
            seeded_agents += 1

        if seeded_agents:
            logger.info("Seeded %d agent configs", seeded_agents)
        else:
            logger.info("Agent configs already seeded")

        # 6. Seed skills (if not already done)
        seeded_skills = 0
        for scope, skill_list in DEFAULT_SKILLS.items():
            for name, source, skill_path in skill_list:
                existing = await db.execute(
                    select(Skill).where(Skill.skill_path == skill_path)
                )
                if existing.scalar_one_or_none():
                    continue
                full_path = TESSL_TILES / skill_path
                content = full_path.read_text("utf-8") if full_path.exists() else None
                db.add(Skill(
                    name=name,
                    source=source,
                    skill_path=skill_path,
                    agent_scope=scope,
                    content_md=content,
                    is_installed=full_path.exists(),
                ))
                seeded_skills += 1

        if seeded_skills:
            logger.info("Seeded %d skills", seeded_skills)
        else:
            logger.info("Skills already seeded")

        # 7. Mark setup as complete (if not already)
        result = await db.execute(
            select(SystemConfig).where(SystemConfig.key == "setup_completed")
        )
        if not result.scalar_one_or_none():
            db.add(SystemConfig(key="setup_completed", value="true"))
            db.add(SystemConfig(key="schema_version", value="004"))
            logger.info("Marked setup_completed=true")

        await db.commit()
        logger.info("Migration complete!")


def main():
    asyncio.run(migrate())


if __name__ == "__main__":
    main()
