"""Seed global pipeline templates and architect agent.

Run: .venv/bin/python -m dashboard.db.seed_templates
Or called automatically from server lifespan.
"""
import asyncio
import uuid
from pathlib import Path

from sqlalchemy import select

BASE = Path(__file__).parent.parent.parent


def _build_linear_graph(stages: list[tuple[str, str]]) -> dict:
    """Build a Drawflow graph from a list of (agent_name, node_type) tuples."""
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
        # Connections
        if i > 0:
            prev_id = str(i)
            node["inputs"] = {"input_1": {"connections": [{"node": prev_id, "input": "output_1"}]}}
        if i < len(stages) - 1:
            next_id = str(i + 2)
            node["outputs"] = {"output_1": {"connections": [{"node": next_id, "output": "input_1"}]}}

        nodes[node_id] = node

    return {"drawflow": {"Home": {"data": nodes}}}


# Template definitions
TEMPLATES = [
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


async def seed_all():
    """Seed global pipeline templates and architect agent."""
    from dashboard.db.engine import async_session
    from dashboard.db.models.pipeline import GlobalPipelineTemplate
    from dashboard.db.models.agent_config import AgentConfig
    from dashboard.db.models.system_config import SystemConfig

    async with async_session() as db:
        # Check if already seeded
        cfg = (await db.execute(
            select(SystemConfig).where(SystemConfig.key == "templates_v2_seeded")
        )).scalar_one_or_none()
        if cfg and cfg.value == "true":
            return False

        # Get superadmin user for created_by
        from dashboard.db.models.user import User
        admin = (await db.execute(
            select(User).where(User.is_superadmin == True).limit(1)
        )).scalar_one_or_none()
        if not admin:
            return False

        # Seed templates
        for tmpl in TEMPLATES:
            existing = (await db.execute(
                select(GlobalPipelineTemplate).where(
                    GlobalPipelineTemplate.name == tmpl["name"]
                )
            )).scalar_one_or_none()
            if existing:
                # Update final_task_status if column was just added
                existing.final_task_status = tmpl["final_task_status"]
                continue

            stages = tmpl["stages"]
            graph = _build_linear_graph(stages)
            stages_order = [s[0] for s in stages]

            gpt = GlobalPipelineTemplate(
                name=tmpl["name"],
                is_active=(tmpl["name"] == "Default Pipeline"),
                graph_json=graph,
                stages_order=stages_order,
                final_task_status=tmpl["final_task_status"],
                created_by=admin.id,
            )
            db.add(gpt)

        # Seed architect agent
        existing_arch = (await db.execute(
            select(AgentConfig).where(
                AgentConfig.project_id == None,
                AgentConfig.agent_name == "architect",
            )
        )).scalar_one_or_none()
        if not existing_arch:
            arch_md = (BASE / "architect" / "instructions.md").read_text(encoding="utf-8")
            db.add(AgentConfig(
                project_id=None,
                agent_name="architect",
                instructions_md=arch_md,
                is_override=False,
            ))

        # Mark as seeded
        if not cfg:
            db.add(SystemConfig(key="templates_v2_seeded", value="true"))
        else:
            cfg.value = "true"

        await db.commit()
        return True


if __name__ == "__main__":
    result = asyncio.run(seed_all())
    print("Seeded" if result else "Already seeded or no admin")
