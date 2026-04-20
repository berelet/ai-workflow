import uuid

import jwt as pyjwt
from fastapi import Depends, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dashboard.auth.jwt import COOKIE_NAME, decode_token
from dashboard.db.engine import get_db
from dashboard.db.models.user import User


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Extract JWT from HTTP-only cookie and return User. Raises 401 on failure."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    try:
        payload = decode_token(token)
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if user.is_blocked:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is blocked")

    return user


async def get_optional_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Same as get_current_user but returns None instead of raising."""
    try:
        return await get_current_user(request, db)
    except HTTPException:
        return None


async def ws_authenticate(websocket: WebSocket, db: AsyncSession) -> User:
    """Authenticate WebSocket connection via HTTP-only cookie (sent automatically on handshake)."""
    token = websocket.cookies.get(COOKIE_NAME)
    if not token:
        await websocket.close(code=4001, reason="Not authenticated")
        raise WebSocketDisconnect(code=4001, reason="Not authenticated")

    try:
        payload = decode_token(token)
    except (pyjwt.ExpiredSignatureError, pyjwt.InvalidTokenError):
        await websocket.close(code=4001, reason="Invalid token")
        raise WebSocketDisconnect(code=4001, reason="Invalid token")

    user_id = payload.get("sub")
    if not user_id:
        await websocket.close(code=4001, reason="Invalid token payload")
        raise WebSocketDisconnect(code=4001, reason="Invalid token payload")

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()

    if not user or user.is_blocked:
        await websocket.close(code=4001, reason="User not found or blocked")
        raise WebSocketDisconnect(code=4001, reason="User not found or blocked")

    return user
