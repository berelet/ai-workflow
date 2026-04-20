"""Notifications API.

Endpoints for listing, reading, and counting in-app notifications.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from dashboard.auth.middleware import get_current_user
from dashboard.db.engine import get_db
from dashboard.db.models.notification import Notification
from dashboard.db.models.user import User

router = APIRouter(tags=["notifications"])


# ---------------------------------------------------------------------------
# GET /api/notifications  –  list notifications for current user
# ---------------------------------------------------------------------------

@router.get("/api/notifications")
async def list_notifications(
    unread_only: bool = False,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    base = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        base = base.where(Notification.is_read == False)  # noqa: E712

    total = (await db.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar_one()

    unread_count = (await db.execute(
        select(func.count()).where(
            Notification.user_id == user.id,
            Notification.is_read == False,  # noqa: E712
        )
    )).scalar_one()

    rows = (await db.execute(
        base.order_by(Notification.created_at.desc())
        .offset(offset)
        .limit(limit)
    )).scalars().all()

    items = [
        {
            "id": str(n.id),
            "type": n.type,
            "title": n.title,
            "body": n.body,
            "link": n.link,
            "is_read": n.is_read,
            "created_at": n.created_at.isoformat(),
        }
        for n in rows
    ]

    return {
        "items": items,
        "total": total,
        "unread_count": unread_count,
        "offset": offset,
        "limit": limit,
    }


# ---------------------------------------------------------------------------
# GET /api/notifications/count  –  lightweight badge counter
# ---------------------------------------------------------------------------

@router.get("/api/notifications/count")
async def notification_count(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    count = (await db.execute(
        select(func.count()).where(
            Notification.user_id == user.id,
            Notification.is_read == False,  # noqa: E712
        )
    )).scalar_one()
    return {"unread_count": count}


# ---------------------------------------------------------------------------
# PATCH /api/notifications/{id}/read  –  mark single notification as read
# ---------------------------------------------------------------------------

@router.patch("/api/notifications/{notification_id}/read")
async def mark_read(
    notification_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        nid = uuid.UUID(notification_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=404, detail="Not found")

    result = await db.execute(
        update(Notification)
        .where(Notification.id == nid, Notification.user_id == user.id)
        .values(is_read=True)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0:  # type: ignore[union-attr]
        raise HTTPException(status_code=404, detail="Notification not found")

    await db.commit()
    return {"id": str(nid), "is_read": True}


# ---------------------------------------------------------------------------
# POST /api/notifications/read-all  –  mark all notifications as read
# ---------------------------------------------------------------------------

@router.post("/api/notifications/read-all")
async def mark_all_read(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        update(Notification)
        .where(
            Notification.user_id == user.id,
            Notification.is_read == False,  # noqa: E712
        )
        .values(is_read=True)
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    return {"updated_count": result.rowcount}  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Helper: create notification (used by other routers)
# ---------------------------------------------------------------------------

async def create_notification(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    type: str,
    title: str,
    body: str | None = None,
    link: str | None = None,
    ref_id: uuid.UUID | None = None,
) -> Notification:
    """Create and flush a notification (caller must commit)."""
    n = Notification(
        user_id=user_id,
        type=type,
        title=title,
        body=body,
        link=link,
        ref_id=ref_id,
    )
    db.add(n)
    await db.flush()
    return n
