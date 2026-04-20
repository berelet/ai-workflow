# AI Workflow

## Описание
Платформа оркестрации AI-разработки. Управление проектами через конвейер AI-агентов (PM → BA → DEV → QA → COMMIT). Веб-дашборд для бэклога, pipeline, агентов, артефактов, терминала. Встроенный транскрайбер.

## Стек
- Python 3.12, FastAPI, uvicorn
- pexpect (интерактивное взаимодействие с CLI-агентами через WebSocket)
- Vanilla JS, CSS (single-file index.html)
- Kiro CLI (агенты)
- Bash (run.sh — менеджер сервисов)

## Путь к проекту
`/home/aimchn/Desktop/ai-workflow`

## Архитектура
- `dashboard/server.py` — FastAPI бэкенд (API + WebSocket терминал)
- `dashboard/index.html` — SPA фронтенд
- `orchestrator/instructions.md` — инструкции оркестратора
- `project-manager/`, `business-analyst/`, `developer/`, `tester/` — агенты с input/output
- `shared/templates/` — шаблоны артефактов
- `projects/` — проекты с бэклогами, pipeline, артефактами
- `run.sh` + `projects.json` — запуск/остановка сервисов
- `venv/` — Python окружение

## Ключевые фичи
1. Мультипроектный дашборд (бэклог, pipeline, артефакты)
2. WebSocket терминал для запуска агентов
3. Настраиваемые пайплайны (dev + discovery)
4. Per-project agent instructions (override глобальных)
5. Deploy (merge develop → master + semver tag)
6. Транскрайбер (запись аудио + Whisper транскрипция)
7. Загрузка изображений к задачам

## Git
- Локальный проект, без remote пока
