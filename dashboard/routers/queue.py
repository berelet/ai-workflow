"""Task Queue API — batch execution of backlog items through a pipeline.

POST /api/queue/create         — create queue + add items
POST /api/queue/{id}/start     — start executing
GET  /api/queue/{id}           — status + items progress
POST /api/queue/{id}/cancel    — cancel running queue
GET  /api/queue/active         — list active/recent queues for project
"""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dashboard.auth.middleware import get_current_user
from dashboard.auth.utils import parse_uuid
from dashboard.db.engine import get_db
from dashboard.db.models.user import User
from dashboard.db.models.project import Project
from dashboard.db.models.backlog import BacklogItem
from dashboard.db.models.pipeline import PipelineDefinition
from dashboard.db.models.task_queue import TaskQueue, TaskQueueItem

router = APIRouter(prefix="/api/queue", tags=["queue"])


# --- Schemas ---

class CreateQueueRequest(BaseModel):
    project_slug: str
    pipeline_id: str | None = None  # uses default if None
    task_ids: list[str]             # backlog item UUIDs or sequence numbers
    stop_on_error: bool = False


# --- Helpers ---

async def _get_project_with_access(db: AsyncSession, user: User, slug: str) -> Project:
    """For mutation endpoints — requires editor+ role."""
    from dashboard.auth.permissions import _resolve_project, require_project_access_or_raise
    project = await _resolve_project(db, slug)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    await require_project_access_or_raise(db, user, project, "editor")
    return project


async def _get_project_read_access(db: AsyncSession, user: User, slug: str) -> Project:
    """For read-only queue access — developer+ allowed."""
    from dashboard.auth.permissions import _resolve_project, require_project_access_or_raise
    project = await _resolve_project(db, slug)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    await require_project_access_or_raise(db, user, project, "developer")
    return project


async def _resolve_pipeline(db: AsyncSession, project: Project, pipeline_id: str | None) -> PipelineDefinition:
    if pipeline_id:
        pd = await db.get(PipelineDefinition, parse_uuid(pipeline_id, "pipeline_id"))
    else:
        result = await db.execute(
            select(PipelineDefinition).where(
                PipelineDefinition.project_id == project.id,
                PipelineDefinition.is_default == True,
            )
        )
        pd = result.scalar_one_or_none()
    if not pd:
        raise HTTPException(status_code=404, detail="Pipeline definition not found")
    return pd


# --- Routes ---

@router.post("/create")
async def create_queue(
    body: CreateQueueRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a task queue with items. Replaces any existing queue for this project."""
    project = await _get_project_with_access(db, user, body.project_slug)
    pipeline_def = await _resolve_pipeline(db, project, body.pipeline_id)

    if not body.task_ids:
        raise HTTPException(status_code=400, detail="No tasks provided")

    # Cancel any running queue for this project and clean up old ones
    from dashboard.services.queue_runner import cancel_queue as runner_cancel
    old_queues = (await db.execute(
        select(TaskQueue).where(TaskQueue.project_id == project.id)
    )).scalars().all()
    for oq in old_queues:
        if oq.status == "running":
            await runner_cancel(oq.id)
        await db.delete(oq)
    await db.flush()

    # Resolve backlog items in order
    items = []
    for i, tid in enumerate(body.task_ids):
        # Try UUID first, then sequence number
        try:
            item_uuid = uuid.UUID(tid)
            bi = await db.get(BacklogItem, item_uuid)
        except ValueError:
            try:
                seq = int(tid)
                result = await db.execute(
                    select(BacklogItem).where(
                        BacklogItem.project_id == project.id,
                        BacklogItem.sequence_number == seq,
                    )
                )
                bi = result.scalar_one_or_none()
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid task ID: {tid}")
        if not bi:
            raise HTTPException(status_code=404, detail=f"Task {tid} not found")
        items.append((bi, i))

    # Create queue
    now = datetime.now(timezone.utc)
    queue = TaskQueue(
        project_id=project.id,
        pipeline_def_id=pipeline_def.id,
        name=f"Batch {now.strftime('%Y-%m-%d %H:%M')}",
        status="pending",
        stop_on_error=body.stop_on_error,
        created_by=user.id,
    )
    db.add(queue)
    await db.flush()

    # Create queue items
    for bi, sort_order in items:
        qi = TaskQueueItem(
            queue_id=queue.id,
            backlog_item_id=bi.id,
            sort_order=sort_order,
        )
        db.add(qi)

    await db.commit()
    await db.refresh(queue)

    return {
        "queue_id": str(queue.id),
        "name": queue.name,
        "status": queue.status,
        "item_count": len(items),
    }


@router.post("/{queue_id}/start")
async def start_queue(
    queue_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Start executing a queue. Returns immediately; execution is server-side."""
    qid = parse_uuid(queue_id, "queue_id")
    queue = await db.get(TaskQueue, qid)
    if not queue:
        raise HTTPException(status_code=404, detail="Queue not found")

    project = await db.get(Project, queue.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    from dashboard.auth.permissions import require_project_access_or_raise
    await require_project_access_or_raise(db, user, project, "editor")

    if queue.status not in ("pending",):
        raise HTTPException(status_code=400, detail=f"Queue is {queue.status}, cannot start")

    from dashboard.services.queue_runner import start_queue as runner_start
    await runner_start(qid, user.id)

    return {"ok": True, "queue_id": str(qid), "status": "running"}


@router.get("/{queue_id}")
async def get_queue(
    queue_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get queue status with all items. Requires developer+ role."""
    qid = parse_uuid(queue_id, "queue_id")
    queue = await db.get(TaskQueue, qid)
    if not queue:
        raise HTTPException(status_code=404, detail="Queue not found")

    # Check read access (developer+) — project already loaded by ID, no need to re-query by slug
    project = await db.get(Project, queue.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    from dashboard.auth.permissions import require_project_access_or_raise
    await require_project_access_or_raise(db, user, project, "developer")

    # Load items with backlog info in a single JOIN query (avoids N+1)
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(TaskQueueItem)
        .options(selectinload(TaskQueueItem.backlog_item))
        .where(TaskQueueItem.queue_id == qid)
        .order_by(TaskQueueItem.sort_order)
    )
    items = result.scalars().all()

    item_data = []
    for qi in items:
        bi = qi.backlog_item
        item_data.append({
            "id": str(qi.id),
            "task_id_display": bi.task_id_display if bi else "?",
            "title": bi.title if bi else "?",
            "sort_order": qi.sort_order,
            "status": qi.status,
            "terminal_session_id": qi.terminal_session_id,
            "started_at": qi.started_at.isoformat() if qi.started_at else None,
            "completed_at": qi.completed_at.isoformat() if qi.completed_at else None,
            "error_message": qi.error_message,
        })

    completed = sum(1 for i in item_data if i["status"] == "completed")
    failed = sum(1 for i in item_data if i["status"] == "failed")

    return {
        "id": str(queue.id),
        "name": queue.name,
        "status": queue.status,
        "stop_on_error": queue.stop_on_error,
        "started_at": queue.started_at.isoformat() if queue.started_at else None,
        "completed_at": queue.completed_at.isoformat() if queue.completed_at else None,
        "items": item_data,
        "total": len(item_data),
        "completed": completed,
        "failed": failed,
    }


@router.post("/{queue_id}/cancel")
async def cancel_queue(
    queue_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a running queue."""
    qid = parse_uuid(queue_id, "queue_id")
    queue = await db.get(TaskQueue, qid)
    if not queue:
        raise HTTPException(status_code=404, detail="Queue not found")

    project = await db.get(Project, queue.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    from dashboard.auth.permissions import require_project_access_or_raise
    await require_project_access_or_raise(db, user, project, "editor")

    if queue.status != "running":
        raise HTTPException(status_code=400, detail=f"Queue is {queue.status}, cannot cancel")

    from dashboard.services.queue_runner import cancel_queue as runner_cancel
    await runner_cancel(qid)

    return {"ok": True}


@router.get("/active/list")
async def list_queues(
    project_slug: str = Query(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List recent queues for a project. Requires developer+ role."""
    project = await _get_project_read_access(db, user, project_slug)

    result = await db.execute(
        select(TaskQueue).where(
            TaskQueue.project_id == project.id,
        ).order_by(TaskQueue.created_at.desc()).limit(10)
    )
    queues = result.scalars().all()

    return {
        "queues": [
            {
                "id": str(q.id),
                "name": q.name,
                "status": q.status,
                "created_at": q.created_at.isoformat(),
                "started_at": q.started_at.isoformat() if q.started_at else None,
                "completed_at": q.completed_at.isoformat() if q.completed_at else None,
            }
            for q in queues
        ]
    }
