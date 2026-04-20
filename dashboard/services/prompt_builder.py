"""Prompt builder for backend-orchestrated pipeline stages.

Ports logic from cli.py build_prompt(), but:
- NO orchestrator instructions (backend manages pipeline flow)
- ADDS completion callback instruction (agent calls API when done)
- Agent receives only its own role instructions + skills + context
"""
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("services.prompt_builder")

BASE = Path(__file__).parent.parent.parent  # /var/www/ai-workflow
TESSL_TILES = BASE / ".tessl" / "tiles"

# Maps pipeline stage to agent directory name
AGENT_DIRS = {
    "PM": "project-manager",
    "PM_REVIEW": "project-manager",
    "BA": "business-analyst",
    "BA_REVIEW": "business-analyst",
    "DESIGN": "designer",
    "DEV": "developer",
    "DEV_REVIEW": "developer",
    "QA": "tester",
    "QA_REVIEW": "tester",
    "PERF": "performance-reviewer",
    "COMMIT": "developer",
    "ARCH": "architect",
    "ARCH_REVIEW": "architect",
}

# Default skills per stage (from AGENTS.md / tessl.json)
DEFAULT_SKILLS = {
    "global": [
        "cisco/software-security/SKILL.md",
        "secondsky/claude-skills/plugins/systematic-debugging/skills/systematic-debugging/SKILL.md",
    ],
    "PM_REVIEW": [
        "alirezarezvani/claude-skills/product-team/product-manager-toolkit/SKILL.md",
    ],
    "BA_REVIEW": [
        "softaworks/agent-toolkit/skills/requirements-clarity/SKILL.md",
    ],
    "DEV_REVIEW": [
        "mindrally/skills/fastapi-python/SKILL.md",
        "softaworks/agent-toolkit/skills/react-dev/SKILL.md",
        "cisco/software-security/SKILL.md",
        "secondsky/claude-skills/plugins/api-testing/skills/api-testing/SKILL.md",
    ],
    "QA_REVIEW": [
        "anthropics/skills/skills/webapp-testing/SKILL.md",
    ],
    "PERF": [
        "secondsky/claude-skills/plugins/web-performance-audit/skills/web-performance-audit/SKILL.md",
        "sickn33/antigravity-awesome-skills/skills/application-performance-performance-optimization/SKILL.md",
        "sickn33/antigravity-awesome-skills/skills/performance-profiling/SKILL.md",
    ],
}


def _load_file(path: Path) -> str:
    if path.exists() and path.stat().st_size > 0:
        return path.read_text("utf-8")
    return ""


def _is_review_stage(stage: str) -> bool:
    upper = stage.upper()
    return "_REVIEW" in upper or upper == "PERF"


class PromptBuilder:
    """Builds prompts for individual pipeline stage agents."""

    def __init__(self, base_path: Path | None = None, tessl_path: Path | None = None):
        self.base = base_path or BASE
        self.tessl = tessl_path or TESSL_TILES

    def load_agent_instructions(
        self,
        stage: str,
        project_dir: str | None = None,
        db_instructions: str | None = None,
    ) -> str:
        """Load agent instructions: DB > project-specific file > global file."""
        # 1. From DB (if provided by caller)
        if db_instructions:
            return db_instructions

        # 2. Project-specific file override
        if project_dir:
            project_agent = Path(project_dir) / ".ai-workflow" / "agents" / f"{stage.lower()}.md"
            if project_agent.exists():
                return _load_file(project_agent)

        # 3. Global agent instructions
        agent_dir = AGENT_DIRS.get(stage.upper(), stage.lower())
        global_path = self.base / agent_dir / "instructions.md"
        return _load_file(global_path)

    def load_skills(
        self,
        stage: str,
        project_skills_config: dict | None = None,
        db_skills: list[dict] | None = None,
    ) -> list[str]:
        """Load skill contents for a review stage.

        Args:
            stage: Pipeline stage (e.g., "DEV_REVIEW", "PERF")
            project_skills_config: Skills config from pipeline-config.json
            db_skills: Skills loaded from DB [{skill_path, content_md}]
        """
        if not _is_review_stage(stage):
            return []

        skills = []
        stage_upper = stage.upper()

        # If DB skills provided, use them directly
        if db_skills:
            for skill in db_skills:
                content = skill.get("content_md", "")
                if content:
                    skills.append(f"=== SKILL: {skill['skill_path']} ===\n{content}")
            return skills

        # Otherwise load from filesystem (project config or defaults)
        config = project_skills_config or DEFAULT_SKILLS

        # Global skills
        for skill_path in config.get("global", DEFAULT_SKILLS.get("global", [])):
            content = _load_file(self.tessl / skill_path)
            if content:
                skills.append(f"=== SKILL: {skill_path} ===\n{content}")

        # Stage-specific skills
        stage_key = stage_upper.lower()
        stage_skills = config.get(stage_key, config.get(stage_upper, DEFAULT_SKILLS.get(stage_upper, [])))
        for skill_path in stage_skills:
            content = _load_file(self.tessl / skill_path)
            if content:
                skills.append(f"=== SKILL: {skill_path} ===\n{content}")

        return skills

    def build_stage_prompt(
        self,
        stage: str,
        task_title: str,
        task_description: str,
        task_id_display: str,
        project_name: str,
        project_description: str = "",
        agent_instructions: str = "",
        skills: list[str] | None = None,
        previous_artifacts: list[dict] | None = None,
        git_branch: str = "",
        git_rules: str = "",
        custom_node_prompt: str = "",
        pipeline_run_id: str = "",
        node_id: str = "",
        callback_url: str = "http://localhost:9000/api/pipeline/complete",
    ) -> str:
        """Build the complete prompt for a single pipeline stage agent.

        Args:
            stage: Pipeline stage name (PM, BA, DEV, etc.)
            task_title: Task title from backlog
            task_description: Task description
            task_id_display: Formatted task ID (AWF-15)
            project_name: Project display name
            project_description: From project.md
            agent_instructions: Agent role instructions (markdown)
            skills: List of formatted skill strings
            previous_artifacts: [{filename, content}] from prior stages
            git_branch: Current git branch name
            git_rules: Git rules markdown
            custom_node_prompt: Custom prompt from Drawflow node config
            pipeline_run_id: For the callback
            node_id: For the callback
            callback_url: Backend callback URL
        """
        parts = []

        # 1. Agent role and instructions
        parts.append(f"# YOUR ROLE: {stage} Agent")
        if agent_instructions:
            parts.append(f"\n## Agent Instructions\n\n{agent_instructions}")

        # 2. Custom node prompt (from Drawflow config)
        if custom_node_prompt:
            parts.append(f"\n## Additional Instructions\n\n{custom_node_prompt}")

        # 3. Project context
        parts.append(f"\n## Project: {project_name}")
        parts.append(f"Task: [{task_id_display}] {task_title}")
        if task_description:
            parts.append(f"\n### Task Description\n\n{task_description}")
        if project_description:
            parts.append(f"\n### Project Context\n\n{project_description}")

        # 4. Previous stage artifacts (input context)
        if previous_artifacts:
            parts.append("\n## Input from Previous Stages\n")
            for art in previous_artifacts:
                parts.append(f"### {art['filename']}\n\n{art['content']}\n")

        # 5. Skills (for review stages)
        if skills:
            parts.append(f"\n## Skills for {stage}\n\n" + "\n\n".join(skills))

        # 6. Git context
        if git_branch:
            parts.append(f"\n## Git\n\nBranch: `{git_branch}`")
        if git_rules and stage.upper() == "COMMIT":
            parts.append(f"\n## Git Rules\n\n{git_rules}")

        # 7. Completion callback
        parts.append(self._build_callback_instruction(
            stage=stage,
            pipeline_run_id=pipeline_run_id,
            node_id=node_id,
            callback_url=callback_url,
            task_id_display=task_id_display,
        ))

        return "\n\n".join(parts)

    def _build_callback_instruction(
        self,
        stage: str,
        pipeline_run_id: str,
        node_id: str,
        callback_url: str,
        task_id_display: str,
    ) -> str:
        """Build the completion callback instruction appended to every prompt."""
        stage_upper = stage.upper()

        base = f"""
## COMPLETION (REQUIRED)

When you finish your work, call the completion API. This is mandatory.

```bash
curl -s -X POST {callback_url} \\
  -H "Content-Type: application/json" \\
  -d '{{"pipeline_run_id":"{pipeline_run_id}","node_id":"{node_id}","status":"completed","artifacts":[{{"filename":"<artifact_name>","path":"<absolute_path>"}}],"message":"<brief summary>"}}'
```

Replace `<artifact_name>`, `<absolute_path>`, and `<brief summary>` with actual values.
"""

        # QA-specific: PASS/FAIL handling
        if stage_upper == "QA":
            base += f"""
### If ANY acceptance criteria FAIL:
Use `"status":"returned"` and `"return_to":"DEV_NODE_ID"` to send work back to developer:
```bash
curl -s -X POST {callback_url} \\
  -H "Content-Type: application/json" \\
  -d '{{"pipeline_run_id":"{pipeline_run_id}","node_id":"{node_id}","status":"returned","artifacts":[{{"filename":"bug-report.md","path":"<path>"}}],"message":"<what failed>","return_to":"<dev_node_id>"}}'
```
"""

        # COMMIT-specific: don't merge, backend handles it
        if stage_upper == "COMMIT":
            base += """
### Important: Do NOT merge to master. Push to the task branch only. The backend handles merge/PR based on project settings.
"""

        return base


# Singleton
prompt_builder = PromptBuilder()
