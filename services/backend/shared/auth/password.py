"""PBKDF2-HMAC-SHA256 password hashing — stdlib only, no external deps."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os


def hash_password(password: str) -> str:
    """Return a storable hash of a plaintext password."""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 260_000)
    return base64.b64encode(salt + dk).decode()


def verify_password(password: str, stored_hash: str) -> bool:
    """Constant-time comparison — returns True if password matches stored_hash."""
    try:
        data = base64.b64decode(stored_hash.encode())
    except Exception:
        return False
    salt, stored_dk = data[:16], data[16:]
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 260_000)
    return hmac.compare_digest(dk, stored_dk)
