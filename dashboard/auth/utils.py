import asyncio
import hashlib
import uuid

import bcrypt

from dashboard.db.models.user import User


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


async def hash_password_async(password: str) -> str:
    return await asyncio.to_thread(hash_password, password)


async def verify_password(password: str, hashed: str) -> bool:
    return await asyncio.to_thread(bcrypt.checkpw, password.encode(), hashed.encode())


def _load_private_key(private_key: str):
    """Load a private key from PEM or OpenSSH-format string. Raises ValueError on failure."""
    from cryptography.hazmat.primitives.serialization import (
        load_pem_private_key, load_ssh_private_key,
    )
    key_bytes = private_key.strip().encode()
    try:
        return load_pem_private_key(key_bytes, password=None)
    except (ValueError, TypeError):
        return load_ssh_private_key(key_bytes, password=None)


def derive_public_key(private_key: str, comment: str = "ai-workflow@dashboard") -> str:
    """Derive OpenSSH-format public key string ('ssh-ed25519 AAAA... comment')."""
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    pk = _load_private_key(private_key)
    pub_bytes = pk.public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH)
    raw = pub_bytes.decode()
    if comment and " " not in raw[raw.find(" ") + 1:]:
        raw = f"{raw} {comment}"
    return raw


def generate_ed25519_keypair(comment: str = "ai-workflow@dashboard") -> tuple[str, str]:
    """Generate a fresh ed25519 keypair. Returns (private_openssh, public_openssh)."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding, PrivateFormat, PublicFormat, NoEncryption,
    )
    key = Ed25519PrivateKey.generate()
    private_bytes = key.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.OpenSSH,
        encryption_algorithm=NoEncryption(),
    )
    public_bytes = key.public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH)
    private_str = private_bytes.decode()
    public_str = public_bytes.decode()
    if comment:
        public_str = f"{public_str} {comment}"
    return private_str, public_str


def ssh_fingerprint(private_key: str) -> str:
    """Extract public key from private key and return its SHA256 fingerprint.
    Falls back to a generic hash if extraction fails (e.g. unsupported key format)."""
    try:
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        pk = _load_private_key(private_key)
        pub_bytes = pk.public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH)
        import base64
        # OpenSSH format: "ssh-rsa AAAA..." — fingerprint the raw base64 part
        parts = pub_bytes.split(b" ", 2)
        raw = base64.b64decode(parts[1]) if len(parts) >= 2 else pub_bytes
        digest = hashlib.sha256(raw).digest()
        return "SHA256:" + base64.b64encode(digest).rstrip(b"=").decode()
    except Exception:
        # Fallback: hash a marker + truncated content (never reveal private key material)
        safe_id = hashlib.sha256(b"fallback:" + private_key.strip().encode()).hexdigest()
        return f"SHA256:{safe_id[:43]}"


def user_to_dict(user: User, include_admin_fields: bool = False) -> dict:
    """Convert User ORM to dict. Admin fields (is_blocked, created_at) are optional."""
    d = {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "lang": user.lang,
        "is_superadmin": user.is_superadmin,
    }
    if include_admin_fields:
        d["is_blocked"] = user.is_blocked
        d["created_at"] = user.created_at.isoformat() if user.created_at else None
    return d


def parse_uuid(value: str, field_name: str = "id") -> uuid.UUID:
    """Parse a UUID string, raise ValueError-safe HTTPException."""
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}: {value}")
