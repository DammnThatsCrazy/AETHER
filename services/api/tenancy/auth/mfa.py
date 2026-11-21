"""Opt-in two-step verification for Aether human sign-in.

A signed-in user enrols an authenticator app (TOTP, RFC 6238) from profile
settings and receives one-time recovery codes. From then on every sign-in
method (password, Google, Apple, Microsoft, Slack, email code) stops after the
first factor with a short-lived challenge, and a session is issued only after
``POST /v1/auth/mfa/verify`` accepts a current code or an unused recovery code.

Aether owns this rather than Auth0 because password sign-in is Aether's own
``/v1/auth/login``; an Auth0 MFA policy would never see those users.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import struct
import time
from typing import Any, Optional
from urllib.parse import quote

from shared.logger.logger import get_logger

logger = get_logger("aether.auth.mfa")

ISSUER = "Aether"
DIGITS = 6
PERIOD = 30
WINDOW = 1  # accept the previous and next 30 s step for clock drift
RECOVERY_CODE_COUNT = 10
CHALLENGE_TTL_SECONDS = 300
CHALLENGE_MAX_ATTEMPTS = 5
PENDING_ENROLMENT_TTL_SECONDS = 900

_MEM: dict[str, tuple[float, str]] = {}


# ── TOTP ────────────────────────────────────────────────────────────────────

def generate_secret() -> str:
    """A 160-bit base32 secret (the length authenticator apps expect)."""
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _counter_code(secret: str, counter: int) -> str:
    padded = secret.upper() + "=" * (-len(secret) % 8)
    key = base64.b32decode(padded)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10 ** DIGITS)).zfill(DIGITS)


def totp(secret: str, at: Optional[float] = None) -> str:
    return _counter_code(secret, int((time.time() if at is None else at) // PERIOD))


def match_totp(secret: str, code: str, *, last_counter: Optional[int] = None,
               at: Optional[float] = None) -> Optional[int]:
    """Return the matched time-step counter, or None.

    A counter at or before ``last_counter`` is refused, so a code observed once
    cannot be replayed within its validity window.
    """
    code = (code or "").strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    now_counter = int((time.time() if at is None else at) // PERIOD)
    for counter in range(now_counter - WINDOW, now_counter + WINDOW + 1):
        if last_counter is not None and counter <= last_counter:
            continue
        if hmac.compare_digest(_counter_code(secret, counter), code):
            return counter
    return None


def provisioning_uri(secret: str, account: str) -> str:
    label = quote(f"{ISSUER}:{account}")
    return (f"otpauth://totp/{label}?secret={secret}&issuer={quote(ISSUER)}"
            f"&algorithm=SHA1&digits={DIGITS}&period={PERIOD}")


# ── Recovery codes ──────────────────────────────────────────────────────────

def generate_recovery_codes() -> list[str]:
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return [
        "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(2))
        for _ in range(RECOVERY_CODE_COUNT)
    ]


def hash_recovery_code(code: str) -> str:
    return hashlib.sha256(code.strip().lower().encode()).hexdigest()


def consume_recovery_code(stored_hashes: list[str], code: str) -> Optional[list[str]]:
    """Return the remaining hashes when ``code`` matches one, else None."""
    digest = hash_recovery_code(code)
    for index, candidate in enumerate(stored_hashes):
        if hmac.compare_digest(candidate, digest):
            return stored_hashes[:index] + stored_hashes[index + 1:]
    return None


# ── Secret sealing ──────────────────────────────────────────────────────────

def _sealer():
    from shared.credentials.local_encrypted import LocalEncryptedCredentialBackend
    return LocalEncryptedCredentialBackend()


def seal_secret(secret: str) -> str:
    return _sealer().seal(secret)


def unseal_secret(sealed: str) -> str:
    return _sealer().unseal(sealed)


# ── Ephemeral state (Redis, in-memory fallback for local) ──────────────────

async def _put(redis: Any, key: str, value: dict, ttl: int) -> None:
    payload = json.dumps(value)
    if redis is not None:
        try:
            await redis.setex(key, ttl, payload)
            return
        except Exception as exc:
            logger.debug(f"mfa redis put failed: {exc}")
    _MEM[key] = (time.time() + ttl, payload)


async def _get(redis: Any, key: str) -> Optional[dict]:
    if redis is not None:
        try:
            raw = await redis.get(key)
            return json.loads(raw) if raw else None
        except Exception as exc:
            logger.debug(f"mfa redis get failed: {exc}")
    entry = _MEM.get(key)
    if not entry or entry[0] < time.time():
        _MEM.pop(key, None)
        return None
    return json.loads(entry[1])


async def _delete(redis: Any, key: str) -> None:
    if redis is not None:
        try:
            await redis.delete(key)
        except Exception:
            pass
    _MEM.pop(key, None)


def _challenge_key(token: str) -> str:
    return f"auth:mfa:challenge:{hashlib.sha256(token.encode()).hexdigest()}"


async def create_challenge(redis: Any, *, tenant_id: str, user_id: str, method: str,
                           plan_tier: str = "") -> str:
    token = secrets.token_urlsafe(32)
    await _put(redis, _challenge_key(token), {
        "tenant_id": tenant_id, "user_id": user_id, "method": method,
        "plan_tier": plan_tier, "attempts": 0,
    }, CHALLENGE_TTL_SECONDS)
    return token


async def load_challenge(redis: Any, token: str) -> Optional[dict]:
    return await _get(redis, _challenge_key(token))


async def record_failed_attempt(redis: Any, token: str, challenge: dict) -> bool:
    """Count a wrong code; return False once the challenge is exhausted (and drop it)."""
    challenge = {**challenge, "attempts": int(challenge.get("attempts", 0)) + 1}
    if challenge["attempts"] >= CHALLENGE_MAX_ATTEMPTS:
        await _delete(redis, _challenge_key(token))
        return False
    await _put(redis, _challenge_key(token), challenge, CHALLENGE_TTL_SECONDS)
    return True


async def drop_challenge(redis: Any, token: str) -> None:
    await _delete(redis, _challenge_key(token))


def _pending_key(user_id: str) -> str:
    return f"auth:mfa:pending:{user_id}"


async def stash_pending_enrolment(redis: Any, user_id: str, sealed_secret: str) -> None:
    await _put(redis, _pending_key(user_id), {"secret": sealed_secret}, PENDING_ENROLMENT_TTL_SECONDS)


async def take_pending_enrolment(redis: Any, user_id: str) -> Optional[str]:
    value = await _get(redis, _pending_key(user_id))
    return value.get("secret") if value else None


async def clear_pending_enrolment(redis: Any, user_id: str) -> None:
    await _delete(redis, _pending_key(user_id))


def is_enabled(user: Optional[dict]) -> bool:
    return bool(user and user.get("mfa_enabled") and user.get("mfa_totp_secret"))
