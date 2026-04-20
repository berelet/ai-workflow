#!/usr/bin/env python3
"""
Comfy CLI — мультипроектный терминал для AI-разработки.

Использование:
  python cli.py                           # Интерактивное меню
  python cli.py <project>                 # Запуск проекта
  python cli.py <project> --task "..."    # С задачей
  python cli.py <project> --pipeline dev  # С пайплайном
  python cli.py <project> --stage PM      # Начать с этапа
  python cli.py <project> --provider claude  # Claude Code
  python cli.py <project> --model sonnet  # Модель

Провайдеры:
  kiro (default)  — Kiro CLI
  claude          — Claude Code

Функции:
  - Загрузка графа пайплайна из JSON
  - Определение текущего этапа из pipeline.md
  - Загрузка skills для review-агентов
  - Загрузка кастомных инструкций агентов
  - Загрузка git-rules.md
"""
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Optional

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

BASE = Path(__file__).parent
PROJECTS = BASE / "projects"
ORCHESTRATOR = BASE / "orchestrator" / "instructions.md"
AGENTS_MD = BASE / "AGENTS.md"
TESSL_TILES = BASE / ".tessl" / "tiles"

# Брендинг
BRAND = "Comfy"
TAGLINE = "AI Development Pipeline"
VERSION = "1.0.0"
SESSION = "comfy"

# Провайдеры CLI и их модели
PROVIDERS = {
    "kiro": {
        "cmd": 'kiro-cli chat --trust-all-tools',
        "check": "kiro-cli",
        "models": {
            "1": ("auto", "Auto (рекомендуется)"),
            "2": ("claude-sonnet-4-6-v1", "Claude Sonnet 4.6"),
            "3": ("claude-3-7-sonnet-v1", "Claude 3.7 Sonnet"),
            "4": ("claude-3-5-sonnet-v2", "Claude 3.5 Sonnet v2"),
            "5": ("custom", "Указать модель вручную"),
        },
        "default_model": "auto",
    },
    "claude": {
        "cmd": 'claude',
        "check": "claude",
        "models": {
            "1": ("sonnet", "Claude Sonnet 4.6 (рекомендуется)"),
            "2": ("opus", "Claude Opus 4.6"),
            "3": ("haiku", "Claude Haiku 4.5"),
            "4": ("claude-sonnet-4-6", "Claude Sonnet 4.6 (полное имя)"),
            "5": ("claude-opus-4-6", "Claude Opus 4.6 (полное имя)"),
            "6": ("custom", "Указать модель вручную"),
        },
        "default_model": "sonnet",
    },
}
DEFAULT_PROVIDER = "kiro"

# Маппинг агентов на папки с инструкциями
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
}

# Дефолтные skills из AGENTS.md
DEFAULT_SKILLS = {
    "global": ["cisco/software-security/SKILL.md", "secondsky/claude-skills/plugins/systematic-debugging/skills/systematic-debugging/SKILL.md"],
    "PM_REVIEW": ["alirezarezvani/claude-skills/product-team/product-manager-toolkit/SKILL.md"],
    "BA_REVIEW": ["softaworks/agent-toolkit/skills/requirements-clarity/SKILL.md"],
    "DEV_REVIEW": [
        "mindrally/skills/fastapi-python/SKILL.md",
        "softaworks/agent-toolkit/skills/react-dev/SKILL.md",
        "cisco/software-security/SKILL.md",
        "secondsky/claude-skills/plugins/api-testing/skills/api-testing/SKILL.md",
    ],
    "QA_REVIEW": ["anthropics/skills/skills/webapp-testing/SKILL.md"],
    "PERF": [
        "secondsky/claude-skills/plugins/web-performance-audit/skills/web-performance-audit/SKILL.md",
        "sickn33/antigravity-awesome-skills/skills/application-performance-performance-optimization/SKILL.md",
        "sickn33/antigravity-awesome-skills/skills/performance-profiling/SKILL.md",
    ],
}


def safe_input(prompt: str = "") -> str:
    """Read input handling partial UTF-8 bytes."""
    sys.stdout.write(prompt)
    sys.stdout.flush()
    try:
        raw = sys.stdin.buffer.readline()
        return raw.decode("utf-8", errors="replace").rstrip("\n\r")
    except EOFError:
        return ""


def load_projects() -> list[str]:
    """Load list of projects."""
    if not PROJECTS.exists():
        return []
    return sorted(p.name for p in PROJECTS.iterdir() if p.is_dir())


def get_project_config(project: str) -> dict:
    """Load pipeline-config.json for project."""
    cfg_path = PROJECTS / project / "pipeline-config.json"
    if cfg_path.exists():
        try:
            return json.loads(cfg_path.read_text("utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def get_ai_workflow_dir(project: str) -> Path:
    """Get .ai-workflow dir from pipeline-config.json's project_dir field."""
    cfg = get_project_config(project)
    if "project_dir" in cfg:
        return Path(cfg["project_dir"]) / ".ai-workflow"
    return PROJECTS / project


def load_file(path: Path) -> str:
    """Load file content if exists."""
    if path.exists() and path.stat().st_size > 0:
        return path.read_text("utf-8")
    return ""


def load_pipeline_graph(project: str, pipeline_id: str) -> dict:
    """Load pipeline graph from JSON file."""
    pipeline_path = PROJECTS / project / "pipelines" / f"{pipeline_id}.json"
    if pipeline_path.exists():
        try:
            data = json.loads(pipeline_path.read_text("utf-8"))
            return data.get("graph", {}).get("drawflow", {}).get("Home", {}).get("data", {})
        except json.JSONDecodeError:
            pass
    return {}


def find_start_node(graph: dict) -> Optional[str]:
    """Find start node (no inputs) in pipeline graph."""
    for node_id, node in graph.items():
        inputs = node.get("inputs", {})
        if not inputs or all(not inp.get("connections") for inp in inputs.values()):
            return node_id
    return list(graph.keys())[0] if graph else None


def get_next_node(graph: dict, current_id: str) -> Optional[str]:
    """Get next node from current node's outputs."""
    if current_id not in graph:
        return None
    outputs = graph[current_id].get("outputs", {})
    for output in outputs.values():
        connections = output.get("connections", [])
        if connections:
            return connections[0].get("node")
    return None


def parse_pipeline_status(pipeline_md: str) -> dict:
    """
    Parse pipeline.md to get current task status.
    Returns: {task_name: {stage: status, ...}, ...}
    """
    tasks = {}
    current_task = None
    current_stages = []

    # Маппинг статусов
    status_map = {
        "done": "done", "✅ done": "done", "✅": "done",
        "in-progress": "in-progress", "⏳ в работе": "in-progress", "⏳": "in-progress",
        "pending": "pending", "⏭": "pending", "skipped": "skipped",
        "bug": "bug", "❌": "bug",
    }

    # Маппинг агентов на этапы
    agent_to_stage = {
        "project-manager": "PM", "pm": "PM",
        "pm review": "PM_REVIEW", "pm_review": "PM_REVIEW",
        "business-analyst": "BA", "ba": "BA",
        "ba review": "BA_REVIEW", "ba_review": "BA_REVIEW",
        "designer": "DESIGN", "design": "DESIGN",
        "developer": "DEV", "dev": "DEV",
        "dev review": "DEV_REVIEW", "dev_review": "DEV_REVIEW",
        "tester": "QA", "qa": "QA",
        "qa review": "QA_REVIEW", "qa_review": "QA_REVIEW",
        "performance-reviewer": "PERF", "perf": "PERF",
        "commit": "COMMIT",
    }

    for line in pipeline_md.split("\n"):
        # Новая задача
        if line.startswith("## "):
            current_task = line.lstrip("# ").strip()
            current_stages = []
            tasks[current_task] = {}
            continue

        # Строка таблицы
        cells = [c.strip() for c in line.split("|") if c.strip()]
        if len(cells) >= 3 and current_task:
            # Ищем агента в ячейках
            stage = None
            status = "pending"
            for cell in cells:
                low = cell.lower()
                if low in agent_to_stage:
                    stage = agent_to_stage[low]
                for k, v in status_map.items():
                    if k in cell.lower():
                        status = v
                        break
            if stage:
                tasks[current_task][stage] = status

    return tasks


def get_current_stage(pipeline_md: str, task_id: Optional[int] = None) -> tuple[str, str]:
    """
    Determine current stage from pipeline.md.
    Returns: (task_name, stage_name) or ("", "PM") if no active task.
    """
    tasks = parse_pipeline_status(pipeline_md)

    # Если указана конкретная задача
    if task_id is not None:
        for task_name in tasks:
            if task_name.startswith(f"#{task_id}") or f"#{task_id}" in task_name:
                stages = tasks[task_name]
                # Найти первый незавершённый этап
                stage_order = ["PM", "PM_REVIEW", "BA", "BA_REVIEW", "DESIGN", "DEV", "DEV_REVIEW", "QA", "QA_REVIEW", "PERF", "COMMIT"]
                for stage in stage_order:
                    if stages.get(stage) not in ("done", "skipped"):
                        return task_name, stage
                return task_name, "done"

    # Найти задачу в процессе
    for task_name, stages in tasks.items():
        for stage, status in stages.items():
            if status in ("in-progress", "bug"):
                return task_name, stage

    # Найти первую незавершённую задачу
    for task_name, stages in tasks.items():
        if any(s not in ("done", "skipped") for s in stages.values()):
            stage_order = ["PM", "PM_REVIEW", "BA", "BA_REVIEW", "DESIGN", "DEV", "DEV_REVIEW", "QA", "QA_REVIEW", "PERF", "COMMIT"]
            for stage in stage_order:
                if stages.get(stage) not in ("done", "skipped"):
                    return task_name, stage

    return "", "PM"


def load_skills_for_stage(stage: str, project_config: dict) -> list[str]:
    """Load skills for a review stage."""
    skills = []

    # Получаем skills из конфига проекта или дефолтные
    config_skills = project_config.get("skills", DEFAULT_SKILLS)

    # Добавляем global skills
    for skill_path in config_skills.get("global", DEFAULT_SKILLS.get("global", [])):
        full_path = TESSL_TILES / skill_path
        content = load_file(full_path)
        if content:
            skills.append(f"=== SKILL: {skill_path} ===\n{content}")

    # Добавляем skills для конкретного этапа
    stage_skills = config_skills.get(stage.lower(), config_skills.get(stage, DEFAULT_SKILLS.get(stage, [])))
    for skill_path in stage_skills:
        full_path = TESSL_TILES / skill_path
        content = load_file(full_path)
        if content:
            skills.append(f"=== SKILL: {skill_path} ===\n{content}")

    return skills


def load_agent_instructions(project: str, stage: str) -> str:
    """Load agent instructions: project-specific or global."""
    ai_dir = get_ai_workflow_dir(project)

    # Сначала проверяем проект-специфичные инструкции
    project_agent_path = ai_dir / "agents" / f"{stage.lower()}.md"
    if project_agent_path.exists():
        return load_file(project_agent_path)

    # Затем глобальные
    agent_dir = AGENT_DIRS.get(stage, stage.lower())
    global_agent_path = BASE / agent_dir / "instructions.md"
    return load_file(global_agent_path)


def load_git_rules(project: str) -> str:
    """Load git-rules.md for project."""
    project_rules = PROJECTS / project / "git-rules.md"
    if project_rules.exists():
        return load_file(project_rules)

    ai_dir = get_ai_workflow_dir(project)
    ai_rules = ai_dir / "git-rules.md"
    return load_file(ai_rules)


def build_prompt(
    project: str,
    task: str = "",
    pipeline_id: str = "default",
    stage: str = "",
    task_id: Optional[int] = None,
) -> str:
    """
    Build comprehensive prompt for CLI.

    Includes:
    - Orchestrator instructions
    - Project context (project.md, backlog.json, pipeline.md)
    - Git rules
    - Agent instructions for current stage
    - Skills for review stages
    - Pipeline graph info
    """
    ai_dir = get_ai_workflow_dir(project)
    project_config = get_project_config(project)

    parts = []

    # 1. Orchestrator instructions (главные инструкции)
    orchestrator_content = load_file(ORCHESTRATOR)
    if orchestrator_content:
        parts.append(f"# ORCHESTRATOR INSTRUCTIONS\n\n{orchestrator_content}")

    # 2. Project context
    parts.append(f"\n# PROJECT: {project}\n")

    project_md = load_file(ai_dir / "project.md")
    if project_md:
        parts.append(f"## project.md\n\n{project_md}")

    backlog_json = load_file(ai_dir / "backlog.json")
    if backlog_json:
        parts.append(f"## backlog.json\n\n```json\n{backlog_json}\n```")

    pipeline_md = load_file(ai_dir / "pipeline.md")
    if pipeline_md:
        parts.append(f"## pipeline.md\n\n{pipeline_md}")

    # 3. Git rules
    git_rules = load_git_rules(project)
    if git_rules:
        parts.append(f"## git-rules.md\n\n{git_rules}")

    # 4. Определение текущего этапа
    if not stage and pipeline_md:
        current_task, stage = get_current_stage(pipeline_md, task_id)
        if current_task:
            parts.append(f"\n## ТЕКУЩАЯ ЗАДАЧА\n\n{current_task}\n\nТекущий этап: **{stage}**")

    # 5. Pipeline graph info
    if pipeline_id:
        graph = load_pipeline_graph(project, pipeline_id)
        if graph:
            start_node = find_start_node(graph)
            parts.append(f"\n## PIPELINE: {pipeline_id}\n")
            parts.append(f"Стартовый узел: {graph.get(start_node, {}).get('data', {}).get('agent', start_node) if start_node else 'N/A'}")

            # Если указан этап — найти его в графе и показать следующий
            if stage and stage != "PM":
                for node_id, node in graph.items():
                    if node.get("data", {}).get("agent") == stage:
                        next_id = get_next_node(graph, node_id)
                        if next_id and next_id in graph:
                            next_agent = graph[next_id].get("data", {}).get("agent", next_id)
                            parts.append(f"Следующий этап после {stage}: {next_agent}")
                        break

    # 6. Agent instructions для текущего этапа
    if stage:
        agent_instructions = load_agent_instructions(project, stage)
        if agent_instructions:
            parts.append(f"\n## AGENT INSTRUCTIONS: {stage}\n\n{agent_instructions}")

    # 7. Skills для review-агентов
    if stage and "_REVIEW" in stage.upper():
        skills = load_skills_for_stage(stage.upper(), project_config)
        if skills:
            parts.append(f"\n## SKILLS FOR {stage}\n\n" + "\n\n".join(skills))

    # 8. Skills для PERF
    if stage and stage.upper() == "PERF":
        skills = load_skills_for_stage("PERF", project_config)
        if skills:
            parts.append(f"\n## SKILLS FOR PERF\n\n" + "\n\n".join(skills))

    # 9. Задача пользователя
    if task:
        parts.append(f"\n## ЗАДАЧА\n\n{task}")
    else:
        parts.append("\n## ЗАДАЧА\n\nЖду команду. Доступные команды: 'статус', 'бэклог', 'возьми задачу N', 'дальше', 'покажи результат'.")

    # Финальный промпт
    header = f"""Ты работаешь с проектом '{project}'.
Pipeline ID: {pipeline_id}
Текущий этап: {stage if stage else 'PM'}

Следуй инструкциям ORCHESTRATOR INSTRUCTIONS выше.
Используй контекст проекта для выполнения задач.
"""

    return header + "\n\n" + "\n\n".join(parts)


def tmux(*args):
    """Run tmux command."""
    return subprocess.run(["tmux"] + list(args), capture_output=True, text=True)


def session_exists() -> bool:
    """Check if tmux session exists."""
    return tmux("has-session", "-t", SESSION).returncode == 0


def list_windows() -> list[str]:
    """List windows in tmux session."""
    r = tmux("list-windows", "-t", SESSION, "-F", "#{window_index}:#{window_name}")
    if r.returncode != 0:
        return []
    return [l.strip() for l in r.stdout.strip().split("\n") if l.strip()]


def build_cli_command(provider: str, prompt_file: Path, model: str = "") -> str:
    """Build CLI command for the specified provider and model."""
    prompt_path = shlex.quote(str(prompt_file))
    provider_config = PROVIDERS.get(provider, PROVIDERS["kiro"])
    base_cmd = provider_config["cmd"]

    # Если модель не указана — используем default
    if not model:
        model = provider_config.get("default_model", "")

    # Добавляем модель если поддерживается (auto = без флага --model)
    model_flag = ""
    if model and model != "auto" and provider in ("kiro", "claude"):
        model_flag = f' --model {model}'

    # Формируем команду
    return f'{base_cmd}{model_flag} "$(cat {prompt_path})"'


def select_model(provider: str) -> str:
    """Interactively select model for provider."""
    provider_config = PROVIDERS.get(provider, PROVIDERS["kiro"])
    models = provider_config.get("models", {})

    if not models:
        # Провайдер не поддерживает выбор модели
        return provider_config.get("default_model", "")

    print(f"\n  \033[1;33mМодели для {provider}:\033[0m")
    for key, (model_id, description) in models.items():
        default_marker = " \033[1;32m(по умолчанию)\033[0m" if model_id == provider_config.get("default_model") else ""
        print(f"    \033[1;34m{key}\033[0m) {description}{default_marker}")

    choice = safe_input("  Модель (Enter = по умолчанию): ").strip()

    if not choice:
        return provider_config.get("default_model", "")

    if choice in models:
        model_id = models[choice][0]
        if model_id == "custom":
            return safe_input("  Введи модель: ").strip()
        return model_id

    # Если введено число которого нет в списке — используем как есть
    return choice


def start_project(
    project: str,
    task: str = "",
    pipeline_id: str = "default",
    stage: str = "",
    task_id: Optional[int] = None,
    provider: str = "kiro",
    model: str = "",
):
    """Start project in tmux window with full context."""
    # Если модель не указана — используем default провайдера
    if not model:
        provider_config = PROVIDERS.get(provider, PROVIDERS["kiro"])
        model = provider_config.get("default_model", "")

    prompt = build_prompt(project, task, pipeline_id, stage, task_id)

    # Write prompt to temp file
    prompt_dir = BASE / ".cli-prompts"
    prompt_dir.mkdir(exist_ok=True)
    prompt_file = prompt_dir / f"{project}.txt"
    prompt_file.write_text(prompt, encoding="utf-8")

    # Build shell command for provider
    shell_cmd = build_cli_command(provider, prompt_file, model)

    if not session_exists():
        tmux("new-session", "-d", "-s", SESSION, "-n", project, "-c", str(BASE), "bash", "-c", shell_cmd)
    else:
        windows = list_windows()
        for w in windows:
            if w.split(":", 1)[1] == project:
                idx = w.split(":")[0]
                tmux("select-window", "-t", f"{SESSION}:{idx}")
                print(f"  Проект {project} уже запущен — переключился на него")
                return
        tmux("new-window", "-t", SESSION, "-n", project, "-c", str(BASE), "bash", "-c", shell_cmd)

    print(f"  \033[33m⚡ {project} запущен в tmux окне\033[0m")
    print(f"  Provider: {provider}")
    if model:
        print(f"  Model: {model}")
    if pipeline_id:
        print(f"  Pipeline: {pipeline_id}")
    if stage:
        print(f"  Этап: {stage}")


def print_menu(projects: list[str]):
    """Print interactive menu."""
    windows = list_windows() if session_exists() else []
    active = {w.split(":", 1)[1] for w in windows}

    # Comfy branding - magenta/purple theme
    print(f"\n\033[1;35m╭───────────────────────────────────╮\033[0m")
    print(f"\033[1;35m│\033[0m     \033[1;37mComfy CLI\033[0m                     \033[1;35m│\033[0m")
    print(f"\033[1;35m│\033[0m     \033[0;90m{TAGLINE}\033[0m           \033[1;35m│\033[0m")
    print(f"\033[1;35m╰───────────────────────────────────╯\033[0m\n")
    print("  Выбери проект:\n")
    for i, p in enumerate(projects, 1):
        tag = " \033[1;35m●\033[0m" if p in active else ""
        print(f"  \033[1;32m{i:2}\033[0m) {p}{tag}")
    print()
    print(f"  \033[1;34m s\033[0m) Статус сессий")
    print(f"  \033[1;34m a\033[0m) Подключиться к tmux")
    print(f"  \033[1;34m q\033[0m) Выход")
    print(f"  \033[1;34m \\\033[0m) Команды")
    print()


def print_commands():
    """Print available slash commands."""
    print(f"""
\033[1;35m╭───────────────────────────────────────────────────╮\033[0m
\033[1;35m│\033[0m  \033[1;37mComfy CLI — Команды\033[0m                            \033[1;35m│\033[0m
\033[1;35m╰───────────────────────────────────────────────────╯\033[0m

  \033[1;33mУправление проектом:\033[0m
    проект <имя>        Переключиться на проект
    статус              Показать pipeline.md
    бэклог              Показать backlog.md

  \033[1;33mРабота с задачами:\033[0m
    возьми задачу N     Взять задачу N из бэклога
    дальше              Следующий этап пайплайна
    покажи результат    Артефакт текущего этапа

  \033[1;33mИнформация:\033[0m
    контекст            Показать project.md
    стек                Показать технологии проекта
    этап                Текущий этап пайплайна

  \033[1;33mДействия:\033[0m
    коммит              Выполнить COMMIT этап
    редизайн            Запустить discovery пайплайн

\033[1;35m╭───────────────────────────────────────────────────╮\033[0m
\033[1;35m│\033[0m  Провайдеры                                      \033[1;35m│\033[0m
\033[1;35m╰───────────────────────────────────────────────────╯\033[0m

  kiro-cli chat --trust-all-tools "..."
  claude --model sonnet "..."

  Сменить: python cli.py <project> --provider claude --model sonnet
""")


def show_status():
    """Show tmux session status."""
    if not session_exists():
        print("  Нет активной сессии Comfy")
        return
    windows = list_windows()
    if not windows:
        print("  Нет окон")
        return
    print(f"\n  tmux сессия: \033[1;36m{SESSION}\033[0m")
    for w in windows:
        idx, name = w.split(":", 1)
        print(f"  \033[33m[{idx}]\033[0m {name}")
    print(f"\n  Подключиться: \033[1mtmux attach -t {SESSION}\033[0m")
    print(f"  Переключение окон: \033[1mCtrl+B, N (след) / P (пред) / номер\033[0m")
    print(f"  Отключиться: \033[1mCtrl+B, D\033[0m\n")


def attach():
    """Attach to tmux session."""
    if not session_exists():
        print("  Нет активной сессии. Сначала запусти проект.")
        return
    os.execvp("tmux", ["tmux", "attach", "-t", SESSION])


def select_pipeline(project: str) -> str:
    """Interactively select pipeline."""
    pipelines_dir = PROJECTS / project / "pipelines"
    if not pipelines_dir.exists():
        return "default"

    pipelines = list(pipelines_dir.glob("*.json"))
    if not pipelines:
        return "default"

    print(f"\n  Доступные пайплайны:")
    for idx, pl_file in enumerate(pipelines, 1):
        try:
            pl_data = json.loads(pl_file.read_text("utf-8"))
            name = pl_data.get("name", pl_file.stem)
            print(f"    \033[1;34m{idx}\033[0m) {name} [{pl_file.stem}]")
        except:
            print(f"    \033[1;34m{idx}\033[0m) {pl_file.stem}")

    choice = safe_input("  Выбери пайплайн (Enter = 1): ").strip()
    if not choice:
        choice = "1"
    if choice.isdigit() and 1 <= int(choice) <= len(pipelines):
        return pipelines[int(choice) - 1].stem
    return pipelines[0].stem


def parse_task_for_id(task: str) -> Optional[int]:
    """Extract task ID from task string like 'возьми задачу 5'."""
    match = re.search(r"задач[ауиюей]?\s*(\d+)", task, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def select_provider() -> str:
    """Interactively select provider."""
    print(f"\n  Выбери провайдер:")
    print(f"    \033[1;34m1\033[0m) kiro-cli (Kiro)")
    print(f"    \033[1;34m2\033[0m) claude (Claude Code)")

    choice = safe_input("  Провайдер (Enter = 1): ").strip()
    if not choice or choice == "1":
        return "kiro"
    elif choice == "2":
        return "claude"
    return "kiro"


def parse_args():
    """Parse command line arguments."""
    args = sys.argv[1:]

    result = {
        "project": "",
        "task": "",
        "pipeline": "default",
        "stage": "",
        "task_id": None,
        "provider": "",  # auto-detect if empty
        "model": "",      # model for provider
    }

    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("--task", "-t"):
            if i + 1 < len(args):
                result["task"] = args[i + 1]
                result["task_id"] = parse_task_for_id(result["task"])
                i += 2
            else:
                i += 1
        elif arg in ("--pipeline", "-p"):
            if i + 1 < len(args):
                result["pipeline"] = args[i + 1]
                i += 2
            else:
                i += 1
        elif arg in ("--stage", "-s"):
            if i + 1 < len(args):
                result["stage"] = args[i + 1].upper()
                i += 2
            else:
                i += 1
        elif arg in ("--provider", "-c"):
            if i + 1 < len(args):
                result["provider"] = args[i + 1].lower()
                i += 2
            else:
                i += 1
        elif arg in ("--model", "-m"):
            if i + 1 < len(args):
                result["model"] = args[i + 1]
                i += 2
            else:
                i += 1
        elif not arg.startswith("-"):
            result["project"] = arg
            i += 1
        else:
            i += 1

    return result


def main():
    """Main entry point."""
    args = parse_args()
    projects = load_projects()

    if not projects:
        print("Нет проектов в projects/")
        return

    # Прямой запуск проекта через CLI аргументы
    if args["project"]:
        if args["project"] not in projects:
            print(f"Проект '{args['project']}' не найден")
            print(f"Доступные проекты: {', '.join(projects)}")
            return

        project = args["project"]
        pipeline_id = args["pipeline"]
        stage = args["stage"]
        task = args["task"]
        task_id = args["task_id"]
        provider = args["provider"] or None

        # Интерактивный выбор пайплайна если не указан
        if not args["pipeline"] or args["pipeline"] == "default":
            pipelines_dir = PROJECTS / project / "pipelines"
            if pipelines_dir.exists() and list(pipelines_dir.glob("*.json")):
                pipeline_id = select_pipeline(project)

        # Интерактивный выбор провайдера если не указан
        if not provider:
            provider = select_provider()

        # Интерактивный выбор модели
        model = args.get("model", "")
        if not model:
            model = select_model(provider)

        start_project(project, task, pipeline_id, stage, task_id, provider, model)

        if len(list_windows()) == 1:
            print(f"\n  \033[1mПодключаюсь к tmux...\033[0m")
            print(f"  Переключение окон: Ctrl+B, N (след) / P (пред) / номер")
            print(f"  Отключиться: Ctrl+B, D\n")
            attach()
        return

    # Интерактивный режим
    while True:
        print_menu(projects)
        try:
            choice = safe_input("  → ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break

        parts = choice.split(maxsplit=1)

        if choice == "q":
            break
        elif choice in ("\\", ""):
            # Показать команды при вводе \ или пустого ввода
            print_commands()
        elif choice == "s":
            show_status()
        elif choice == "a":
            attach()
        elif parts[0].isdigit() and 1 <= int(parts[0]) <= len(projects):
            proj = projects[int(parts[0]) - 1]
            task = ""
            task_id = None

            if len(parts) > 1 and parts[1] != "":
                task = parts[1]
                task_id = parse_task_for_id(task)
            else:
                task = safe_input("  Задача (Enter = интерактив): ").strip()
                task_id = parse_task_for_id(task)

            pipeline_id = select_pipeline(proj)
            provider = select_provider()

            # Спросить про этап если есть активная задача
            ai_dir = get_ai_workflow_dir(proj)
            pipeline_md = load_file(ai_dir / "pipeline.md")
            if pipeline_md:
                current_task, current_stage = get_current_stage(pipeline_md, task_id)
                if current_task and current_stage not in ("done", ""):
                    print(f"\n  Текущая задача: {current_task}")
                    print(f"  Текущий этап: {current_stage}")
                    stage_input = safe_input("  Этап (Enter = текущий): ").strip().upper()
                    if stage_input:
                        stage = stage_input
                    else:
                        stage = current_stage
                else:
                    stage = safe_input("  Начать с этапа (Enter = PM): ").strip().upper()
            else:
                stage = safe_input("  Начать с этапа (Enter = PM): ").strip().upper()

            # Выбор модели
            model = select_model(provider)

            start_project(proj, task, pipeline_id, stage, task_id, provider, model)

            if len(list_windows()) == 1:
                print(f"\n  \033[1mПодключаюсь к tmux...\033[0m")
                print(f"  Переключение окон: Ctrl+B, N (след) / P (пред) / номер")
                print(f"  Отключиться: Ctrl+B, D\n")
                attach()
        else:
            print("  Неверный ввод")


if __name__ == "__main__":
    main()