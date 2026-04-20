#!/bin/bash
# Update task status in DB + re-dump backlog files (exclude done/archived).
# Usage: update-task-status.sh <project-slug> <task-number> <status>
# Example: update-task-status.sh ai-workflow 23 done

set -e
cd "$(dirname "$0")"

PROJECT="${1:?Usage: update-task-status.sh <project> <task-number> <status>}"
TASK_NUM="${2:?Usage: update-task-status.sh <project> <task-number> <status>}"
STATUS="${3:?Usage: update-task-status.sh <project> <task-number> <status>}"

.venv/bin/python -c "
import asyncio, sys, json
sys.path.insert(0, '.')
from pathlib import Path
from dotenv import load_dotenv; load_dotenv('.env')
from sqlalchemy import select
from dashboard.db.engine import async_session
from dashboard.db.models.backlog import BacklogItem
from dashboard.db.models.project import Project

async def update():
    async with async_session() as db:
        proj = (await db.execute(select(Project).where(Project.slug == '$PROJECT'))).scalar_one_or_none()
        if not proj:
            print('ERROR: project not found'); return
        bi = (await db.execute(select(BacklogItem).where(
            BacklogItem.project_id == proj.id, BacklogItem.sequence_number == $TASK_NUM
        ))).scalar_one_or_none()
        if not bi:
            print('ERROR: task not found'); return
        bi.status = '$STATUS'
        await db.commit()
        print(f'OK: task #$TASK_NUM → $STATUS')

        # Re-dump backlog files (exclude done/archived)
        result = await db.execute(
            select(BacklogItem).where(
                BacklogItem.project_id == proj.id,
                BacklogItem.status.notin_(['done', 'archived']),
            ).order_by(BacklogItem.sort_order, BacklogItem.sequence_number)
        )
        items = [{'id': b.sequence_number, 'task': b.title, 'description': b.description or '', 'priority': b.priority or 'medium', 'status': b.status or 'todo'} for b in result.scalars().all()]

        cwd = '.'
        cfg_path = Path('projects/$PROJECT/pipeline-config.json')
        if cfg_path.exists():
            cfg = json.loads(cfg_path.read_text())
            if 'project_dir' in cfg:
                cwd = cfg['project_dir']
        ai_dir = Path(cwd) / '.ai-workflow'
        ai_dir.mkdir(parents=True, exist_ok=True)
        (ai_dir / 'backlog.json').write_text(json.dumps(items, ensure_ascii=False, indent=2))
        lines = ['# Бэклог', '', '| # | Задача | Приоритет | Статус |', '|---|--------|-----------|--------|']
        for i in items:
            lines.append(f'| {i[\"id\"]} | {i[\"task\"]} | {i[\"priority\"]} | {i[\"status\"]} |')
        (ai_dir / 'backlog.md').write_text('\n'.join(lines) + '\n')
        print(f'Backlog files updated ({len(items)} active tasks)')

asyncio.run(update())
"
