"""6-digit OTP for email verification — Redis with in-memory fallback."""
from __future__ import annotations

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


async def store_otp(email: str, otp: str, redis: Optional[Any] = None) -> None:
    """Persist OTP for up to 10 minutes."""
    key = _redis_key(email)
    if redis is not None:
        try:
            await redis.setex(key, _OTP_TTL, otp)
            return
        except Exception as e:
            logger.debug(f"OTP redis store failed: {e}")
    _MEM_STORE[key] = {"otp": otp, "expires": time.time() + _OTP_TTL}


async def verify_otp(email: str, code: str, redis: Optional[Any] = None) -> bool:
    """Return True if code matches; always deletes the record on match."""
    key = _redis_key(email)
    if redis is not None:
        try:
            stored = await redis.get(key)
            if stored and stored == code:
                await redis.delete(key)
                return True
            return False
        except Exception as e:
            logger.debug(f"OTP redis verify failed: {e}")

    entry = _MEM_STORE.get(key)
    if entry and entry["expires"] > time.time() and entry["otp"] == code:
        _MEM_STORE.pop(key, None)
        return True
    return False


async def delete_otp(email: str, redis: Optional[Any] = None) -> None:
    key = _redis_key(email)
    if redis is not None:
        try:
            await redis.delete(key)
        except Exception:
            pass
    _MEM_STORE.pop(key, None)
