import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from dashboard.auth.jwt import create_access_token, set_token_cookie, clear_token_cookie
from dashboard.auth.middleware import get_current_user
from dashboard.auth.utils import (
    hash_password_async, verify_password, ssh_fingerprint, user_to_dict,
    parse_uuid, generate_ed25519_keypair, derive_public_key,
)
from dashboard.db.engine import get_db
from dashboard.db.models.user import User
from dashboard.db.models.ssh_key import SSHKey

router = APIRouter(prefix="/api/auth", tags=["auth"])

MAX_PASSWORD_LENGTH = 128


# --- Pydantic schemas ---

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=MAX_PASSWORD_LENGTH)
    display_name: str = Field(min_length=1, max_length=100)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


class UpdateProfileRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    lang: str | None = None
    current_password: str | None = None
    new_password: str | None = Field(default=None, min_length=8, max_length=MAX_PASSWORD_LENGTH)


class AddSSHKeyRequest(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    private_key: str = Field(min_length=1)


class GenerateSSHKeyRequest(BaseModel):
    label: str = Field(min_length=1, max_length=100)


# --- Helpers ---

async def _require_setup_complete(db: AsyncSession):
    """Block auth endpoints until setup wizard is finished."""
    from dashboard.db.models.system_config import SystemConfig
    result = await db.execute(select(SystemConfig).where(SystemConfig.key == "setup_completed"))
    cfg = result.scalar_one_or_none()
    if not cfg or cfg.value != "true":
        raise HTTPException(status_code=503, detail="Setup not completed. Complete the setup wizard first.")


# --- Routes ---

@router.post("/register")
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    await _require_setup_complete(db)

    existing = await db.execute(select(User).where(User.email == body.email.lower()))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    password_hash = await hash_password_async(body.password)
    user = User(
        email=body.email.lower(),
        password_hash=password_hash,
        display_name=body.display_name,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(user.id, user.email, user.is_superadmin)
    response = JSONResponse(content={"user": user_to_dict(user)})
    set_token_cookie(response, token)
    return response


@router.post("/login")
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    await _require_setup_complete(db)
    result = await db.execute(select(User).where(User.email == body.email.lower()))
    user = result.scalar_one_or_none()

    if not user or not await verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if user.is_blocked:
        raise HTTPException(status_code=403, detail="User is blocked")

    token = create_access_token(user.id, user.email, user.is_superadmin)
    response = JSONResponse(content={"user": user_to_dict(user)})
    set_token_cookie(response, token)
    return response


@router.post("/logout")
async def logout():
    response = JSONResponse(content={"ok": True})
    clear_token_cookie(response)
    return response


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return {"user": user_to_dict(user)}


@router.put("/me")
async def update_profile(
    body: UpdateProfileRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.display_name is not None:
        user.display_name = body.display_name
    if body.lang is not None:
        if body.lang not in ("uk", "en"):
            raise HTTPException(status_code=400, detail="Language must be 'uk' or 'en'")
        user.lang = body.lang
    if body.new_password is not None:
        if not body.current_password:
            raise HTTPException(status_code=400, detail="Current password required")
        if not await verify_password(body.current_password, user.password_hash):
            raise HTTPException(status_code=400, detail="Current password is incorrect")
        user.password_hash = await hash_password_async(body.new_password)

    await db.commit()
    await db.refresh(user)

    response_data = {"user": user_to_dict(user)}
    if body.new_password is not None:
        token = create_access_token(user.id, user.email, user.is_superadmin)
        response = JSONResponse(content=response_data)
        set_token_cookie(response, token)
        return response

    return response_data


# --- SSH Keys ---

@router.get("/me/ssh-keys")
async def list_ssh_keys(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(SSHKey).where(SSHKey.user_id == user.id).order_by(SSHKey.created_at)
    )
    keys = result.scalars().all()
    return {
        "keys": [
            {
                "id": str(k.id),
                "label": k.label,
                "fingerprint": k.public_key_fingerprint,
                "created_at": k.created_at.isoformat(),
            }
            for k in keys
        ]
    }


@router.post("/me/ssh-keys")
async def add_ssh_key(
    body: AddSSHKeyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from dashboard.auth.crypto import encrypt_ssh_key
    encrypted = encrypt_ssh_key(body.private_key)
    fingerprint = ssh_fingerprint(body.private_key)

    key = SSHKey(
        user_id=user.id,
        label=body.label,
        encrypted_private_key=encrypted,
        public_key_fingerprint=fingerprint,
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)

    return {
        "key": {
            "id": str(key.id),
            "label": key.label,
            "fingerprint": key.public_key_fingerprint,
            "created_at": key.created_at.isoformat(),
        }
    }


@router.post("/me/ssh-keys/generate")
async def generate_ssh_key(
    body: GenerateSSHKeyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a fresh ed25519 keypair on the server.
    Stores private (Fernet-encrypted) and returns the public key for the user
    to add to their git provider (GitLab/GitHub)."""
    from dashboard.auth.crypto import encrypt_ssh_key

    comment = f"ai-workflow:{user.email}"
    private_str, public_str = generate_ed25519_keypair(comment=comment)
    encrypted = encrypt_ssh_key(private_str)
    fingerprint = ssh_fingerprint(private_str)

    key = SSHKey(
        user_id=user.id,
        label=body.label,
        encrypted_private_key=encrypted,
        public_key_fingerprint=fingerprint,
    )
    db.add(key)
    await db.commit()
    await db.refresh(key)

    return {
        "key": {
            "id": str(key.id),
            "label": key.label,
            "fingerprint": key.public_key_fingerprint,
            "public_key": public_str,
            "created_at": key.created_at.isoformat(),
        }
    }


@router.get("/me/ssh-keys/{key_id}/public")
async def get_ssh_public_key(
    key_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the OpenSSH public key for an existing key. Used to re-display
    the public key when the user wants to copy it again (e.g. forgot to add
    to GitLab the first time)."""
    from dashboard.auth.crypto import decrypt_ssh_key
    kid = parse_uuid(key_id, "key_id")
    result = await db.execute(
        select(SSHKey).where(SSHKey.id == kid, SSHKey.user_id == user.id)
    )
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=404, detail="SSH key not found")

    try:
        private_str = decrypt_ssh_key(key.encrypted_private_key)
        public_str = derive_public_key(private_str, comment=f"ai-workflow:{user.email}")
    except Exception:
        raise HTTPException(status_code=500, detail="Cannot derive public key from stored key")

    return {"public_key": public_str, "fingerprint": key.public_key_fingerprint}


@router.delete("/me/ssh-keys/{key_id}")
async def delete_ssh_key(
    key_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    kid = parse_uuid(key_id, "key_id")
    result = await db.execute(
        select(SSHKey).where(SSHKey.id == kid, SSHKey.user_id == user.id)
    )
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=404, detail="SSH key not found")

    await db.delete(key)
    await db.commit()
    return {"ok": True}
