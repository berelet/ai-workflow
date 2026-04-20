#!/bin/bash
# Get full task info from DB: title, description, status, artifacts (text content).
# Usage: get-task-info.sh <project-slug> <task-number>
# Output: JSON with task data + artifact contents

set -e
cd "$(dirname "$0")"

PROJECT="${1:?Usage: get-task-info.sh <project> <task-number>}"
TASK_NUM="${2:?Usage: get-task-info.sh <project> <task-number>}"

python3 -c "
import asyncio, json, sys
sys.path.insert(0, '.')
from dotenv import load_dotenv; load_dotenv('.env')
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from dashboard.db.engine import async_session
from dashboard.db.models.backlog import BacklogItem
from dashboard.db.models.artifact import Artifact
from dashboard.db.models.project import Project

async def get_info():
    async with async_session() as db:
        proj = (await db.execute(select(Project).where(Project.slug == '$PROJECT'))).scalar_one_or_none()
        if not proj:
            print(json.dumps({'error': 'project not found'})); return
        bi = (await db.execute(
            select(BacklogItem).where(
                BacklogItem.project_id == proj.id,
                BacklogItem.sequence_number == $TASK_NUM,
            )
        )).scalar_one_or_none()
        if not bi:
            print(json.dumps({'error': 'task not found'})); return

        arts = (await db.execute(
            select(Artifact).where(Artifact.backlog_item_id == bi.id)
            .order_by(Artifact.stage, Artifact.created_at)
        )).scalars().all()

        artifacts = []
        for a in arts:
            entry = {'name': a.name, 'stage': a.stage or '', 'type': a.artifact_type}
            if a.content_text:
                entry['content'] = a.content_text
            elif a.local_path:
                try:
                    from pathlib import Path
                    entry['content'] = Path(a.local_path).read_text('utf-8')
                except:
                    entry['content'] = '[file not readable]'
            artifacts.append(entry)

        result = {
            'id': bi.sequence_number,
            'title': bi.title,
            'description': bi.description or '',
            'priority': bi.priority,
            'status': bi.status,
            'artifacts': artifacts,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))

asyncio.run(get_info())
"
