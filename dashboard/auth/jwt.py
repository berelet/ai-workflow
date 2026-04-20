import os
import uuid
from datetime import datetime, timedelta, timezone

import jwt

_raw_secret = os.getenv("JWT_SECRET_KEY", "")
_UNSAFE_DEFAULTS = {"", "change-me-in-production", "unsafe-dev-fallback"}
SETUP_MODE = _raw_secret in _UNSAFE_DEFAULTS

if SETUP_MODE:
    import warnings
    warnings.warn(
        "JWT_SECRET_KEY is not set or uses a default value. "
        "Auth will NOT work until a proper secret is configured via setup wizard.",
        stacklevel=1,
    )
    _raw_secret = "unsafe-dev-fallback"

SECRET_KEY = _raw_secret


def _require_configured():
    """Raise if JWT_SECRET_KEY is not properly configured. Called by auth operations."""
    if SETUP_MODE:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=503,
            detail="Server not configured. Complete the setup wizard first.",
        )
ALGORITHM = "HS256"
TOKEN_EXPIRE_DAYS = 365
COOKIE_NAME = "token"
SECURE_COOKIES = os.getenv("SECURE_COOKIES", "false").lower() == "true"


def create_access_token(user_id: uuid.UUID, email: str, is_superadmin: bool) -> str:
    _require_configured()
    payload = {
        "sub": str(user_id),
        "email": email,
        "is_superadmin": is_superadmin,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(days=TOKEN_EXPIRE_DAYS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and validate JWT. Raises jwt.ExpiredSignatureError or jwt.InvalidTokenError."""
    _require_configured()
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])


def set_token_cookie(response, token: str) -> None:
    """Set HTTP-only cookie on a FastAPI Response."""
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=SECURE_COOKIES,
        path="/",
        max_age=TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
    )


def clear_token_cookie(response) -> None:
    """Clear the auth cookie."""
    response.delete_cookie(
        key=COOKIE_NAME,
        httponly=True,
        samesite="lax",
        secure=SECURE_COOKIES,
        path="/",
    )
