import base64
import os

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes


def _get_fernet() -> Fernet:
    """Derive a Fernet key from JWT_SECRET_KEY via HKDF."""
    from dashboard.auth.jwt import SECRET_KEY
    secret = SECRET_KEY.encode()
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"aiworkflow-ssh-keys",
        info=b"fernet-key",
    )
    key = base64.urlsafe_b64encode(hkdf.derive(secret))
    return Fernet(key)


def encrypt_ssh_key(plaintext: str) -> str:
    """Encrypt an SSH private key. Returns base64-encoded ciphertext."""
    f = _get_fernet()
    return f.encrypt(plaintext.encode()).decode()


def decrypt_ssh_key(ciphertext: str) -> str:
    """Decrypt an SSH private key."""
    f = _get_fernet()
    return f.decrypt(ciphertext.encode()).decode()
