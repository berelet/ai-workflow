"""Shared helper functions used across routers.

Extracted from the monolithic server.py for reuse.
These helpers work with the legacy file-based storage.
For DB-backed projects, routers will use SQLAlchemy directly.
"""
import json
from pathlib import Path

BASE = Path(__file__).parent.parent  # /var/www/ai-workflow
PROJECTS = BASE / "projects"
UPLOADS = BASE / "uploads"
UPLOADS.mkdir(exist_ok=True)

AGENTS = [
    "orchestrator", "project-manager", "business-analyst", "designer",
    "developer", "tester", "performance-reviewer",
    "discovery-interview", "discovery-analysis",
    "discovery-decomposition", "discovery-confirmation",
]


def safe_path_param(value: str) -> str:
    """Validate a path parameter (project name, task_id, filename) to prevent traversal.
    Rejects values containing '..' or path separators."""
    if not value or ".." in value or "/" in value or "\\" in value:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Invalid path parameter: {value}")
    return value


def read_md(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def write_md(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def get_ai_workflow_dir(name: str) -> Path:
    """Get .ai-workflow dir from pipeline-config.json's project_dir field."""
    name = safe_path_param(name)
    cfg_path = PROJECTS / name / "pipeline-config.json"
    if cfg_path.exists():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        if "project_dir" in cfg:
            return Path(cfg["project_dir"]) / ".ai-workflow"
    return PROJECTS / name




def parse_pipeline(text: str) -> list[dict]:
    cards = []
    task_name = ""
    agent_to_stage = {
        "project-manager": "PM", "pm": "PM",
        "pm review": "PM_REVIEW", "pm skills review": "PM_REVIEW", "pm_review": "PM_REVIEW",
        "business-analyst": "BA", "ba": "BA",
        "ba review": "BA_REVIEW", "ba skills review": "BA_REVIEW", "ba_review": "BA_REVIEW",
        "designer": "DESIGN", "design": "DESIGN",
        "developer": "DEV", "dev": "DEV",
        "dev review": "DEV_REVIEW", "dev skills review": "DEV_REVIEW", "dev_review": "DEV_REVIEW",
        "tester": "QA", "qa": "QA",
        "qa review": "QA_REVIEW", "qa skills review": "QA_REVIEW", "qa_review": "QA_REVIEW",
        "performance-reviewer": "PERF", "perf": "PERF",
    }
    status_map = {
        "done": "done", "✅ done": "done", "✅": "done",
        "in-progress": "in-progress", "⏳ в работе": "in-progress", "⏳": "in-progress",
        "bug": "bug", "❌": "bug", "todo": "todo",
    }
    for line in text.split("\n"):
        if line.startswith("## "):
            task_name = line.lstrip("# ").strip()
            continue
        cells = [c.strip() for c in line.split("|") if c.strip()]
        if len(cells) < 3:
            continue
        for cell in cells:
            low = cell.lower()
            if low in agent_to_stage:
                stage = agent_to_stage[low]
                status = "in-progress"
                for c2 in cells:
                    for k, v in status_map.items():
                        if k in c2.lower():
                            status = v
                            break
                cards.append({"task": task_name or "Задача", "stage": stage, "status": status})
                break
    return cards
