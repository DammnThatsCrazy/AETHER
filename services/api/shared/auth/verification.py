"""6-digit OTP for email verification, held in the shared cache (memory only without one)."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import Any, Optional

from shared.logger.logger import get_logger

logger = get_logger("aether.auth.verification")

_OTP_TTL = 600        # 10-minute window
_MEM_STORE: dict[str, dict] = {}  # in-memory fallback


def generate_otp() -> str:
    """Return a 6-digit numeric OTP."""
    return str(secrets.randbelow(900_000) + 100_000)


def _redis_key(email: str) -> str:
    return f"auth:otp:{email.lower()}"


def _same_code(stored: str, code: str) -> bool:
    """Constant-time comparison that never raises on non-ASCII input.

    ``hmac.compare_digest`` refuses non-ASCII ``str``, so a code such as
    fullwidth digits would otherwise surface as a server error instead of a
    wrong code. Comparing UTF-8 bytes keeps the timing guarantee.
    """
    return hmac.compare_digest(stored.encode("utf-8"), code.encode("utf-8"))


def _consumed_key(key: str, otp: str) -> str:
    return f"{key}:consumed:{hashlib.sha256(otp.encode()).hexdigest()[:32]}"


async def store_otp(email: str, otp: str, cache: Optional[Any] = None) -> None:
    """Persist OTP for up to 10 minutes in the shared cache (memory only without one)."""
    key = _redis_key(email)
    if cache is not None:
        await cache.set(key, otp, _OTP_TTL)
        return
    _MEM_STORE[key] = {"otp": otp, "expires": time.time() + _OTP_TTL}


async def verify_otp(email: str, code: str, cache: Optional[Any] = None) -> bool:
    """Return True if code matches, exactly once per issued code.

    The comparison is constant time, and a match is spent with an atomic
    ``set_nx`` claim before the record is deleted, so two overlapping requests
    with the right code cannot both pass.
    """
    key = _redis_key(email)
    code = (code or "").strip()
    if cache is not None:
        stored = await cache.get(key)
        if not stored or not _same_code(str(stored), code):
            return False
        if not await cache.set_nx(_consumed_key(key, str(stored)), "1", _OTP_TTL):
            return False
        await cache.delete(key)
        return True

    entry = _MEM_STORE.get(key)
    if entry and entry["expires"] > time.time() and _same_code(entry["otp"], code):
        _MEM_STORE.pop(key, None)
        return True
    return False


async def delete_otp(email: str, cache: Optional[Any] = None) -> None:
    key = _redis_key(email)
    if cache is not None:
        await cache.delete(key)
        return
    _MEM_STORE.pop(key, None)
