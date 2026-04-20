"""Agent and skills API routes (DB-backed).

GET  /api/agents                        - list all agent names
GET  /api/agents/{agent}/instructions   - get global agent instructions
PUT  /api/agents/{agent}/instructions   - update global agent instructions (superadmin only)
GET  /api/skills                        - installed skills with agent mappings
"""
import json
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from dashboard.auth.middleware import get_current_user
from dashboard.auth.permissions import require_superadmin
from dashboard.db.engine import get_db
from dashboard.db.models.user import User
from dashboard.db.models.agent_config import AgentConfig
from dashboard.helpers import BASE, AGENTS

router = APIRouter(tags=["agents"])


class InstructionsBody(BaseModel):
    content: str


@router.get("/api/agents")
async def list_agents(user: User = Depends(get_current_user), db=Depends(get_db)):
    """List agent names that have global configs in DB, merged with known AGENTS list."""
    result = await db.execute(
        select(AgentConfig.agent_name).where(AgentConfig.project_id == None)
    )
    db_agents = {row[0] for row in result.all()}
    return sorted(set(AGENTS) | db_agents)


@router.get("/api/agents/{agent}/instructions")
async def get_instructions(agent: str, user: User = Depends(get_current_user), db=Depends(get_db)):
    """Get global agent instructions from DB."""
    result = await db.execute(
        select(AgentConfig).where(
            AgentConfig.project_id == None,
            AgentConfig.agent_name == agent,
        )
    )
    ac = result.scalar_one_or_none()
    if ac:
        return {"content": ac.instructions_md}
    return {"content": ""}


@router.put("/api/agents/{agent}/instructions")
async def update_instructions(
    agent: str,
    body: InstructionsBody,
    user: User = Depends(require_superadmin),
    db=Depends(get_db),
):
    """Update global agent instructions. Requires superadmin."""
    result = await db.execute(
        select(AgentConfig).where(
            AgentConfig.project_id == None,
            AgentConfig.agent_name == agent,
        )
    )
    ac = result.scalar_one_or_none()
    if ac:
        ac.instructions_md = body.content
    else:
        db.add(AgentConfig(
            project_id=None,
            agent_name=agent,
            instructions_md=body.content,
            is_override=False,
        ))
    await db.commit()
    return {"ok": True}


@router.get("/api/skills")
def get_skills(user: User = Depends(get_current_user)):
    """Parse AGENTS.md and tessl.json to return installed skills with agent mappings."""
    skills = []
    agents_md = BASE / "docs" / "AGENTS.md"
    tessl_json = BASE / "tessl.json"

    installed = {}
    if tessl_json.exists():
        data = json.loads(tessl_json.read_text())
        for tile, info in data.get("dependencies", {}).items():
            if tile.startswith("tessl/"):
                continue
            installed[tile] = info.get("version", "")[:12]

    if agents_md.exists():
        text = agents_md.read_text()
        current_section = "global"
        for line in text.split("\n"):
            if line.startswith("## "):
                section = line[3:].strip().lower()
                if "global" in section:
                    current_section = "global"
                elif "backend" in section or "dev agent" in section and "fastapi" in section:
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
                skill_path = ""
                skill_desc = ""
                idx = text.index(line)
                after = text[idx + len(line):]
                for next_line in after.split("\n"):
                    next_line = next_line.strip()
                    if next_line.startswith("@"):
                        parts = next_line.split(maxsplit=1)
                        skill_path = parts[0][1:]
                        if len(parts) > 1:
                            raw_desc = parts[1]
                            skill_desc = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', raw_desc)
                            if skill_desc:
                                skill_desc = skill_desc[0].upper() + skill_desc[1:]
                        break
                    if next_line.startswith("##"):
                        break
                skills.append({
                    "name": skill_label,
                    "source": skill_source,
                    "description": skill_desc,
                    "agent": current_section,
                    "path": skill_path,
                    "installed": any(skill_source.split("/")[0] in t for t in installed) if "/" in skill_source else skill_source in installed,
                })

    return {"skills": skills, "installed_tiles": installed}
