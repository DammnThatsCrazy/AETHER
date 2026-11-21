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

import asyncio
import base64
import hashlib
import hmac
import json
import secrets
import struct
import time
from contextlib import asynccontextmanager
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


# ── Ephemeral state (shared cache, in-memory fallback for local) ───────────
#
# Challenges, pending enrolments, single-use claims and per-user locks live in
# the platform's shared ``CacheClient`` (Redis or DynamoDB in deployed
# environments), so a follow-up request can land on any API process. The
# process-local ``_MEM`` fallback is only for a missing cache (local tests).

USER_LOCK_TTL_SECONDS = 10
USER_LOCK_WAIT_SECONDS = 3.0
_USER_LOCK_POLL_SECONDS = 0.05


def get_cache() -> Any:
    """The shared cache client, or None when the platform registry is unavailable."""
    try:
        from dependencies.providers import get_registry
        return getattr(get_registry(), "cache", None)
    except Exception as exc:  # noqa: BLE001 - local tooling without a registry
        logger.debug(f"mfa cache unavailable: {exc}")
        return None


def _mem_get(key: str) -> Optional[str]:
    entry = _MEM.get(key)
    if not entry or entry[0] < time.time():
        _MEM.pop(key, None)
        return None
    return entry[1]


async def _put(cache: Any, key: str, value: dict, ttl: int) -> None:
    payload = json.dumps(value)
    if cache is not None:
        await cache.set(key, payload, ttl)
        return
    _MEM[key] = (time.time() + ttl, payload)


async def _get(cache: Any, key: str) -> Optional[dict]:
    raw = await cache.get(key) if cache is not None else _mem_get(key)
    return json.loads(raw) if raw else None


async def _delete(cache: Any, key: str) -> None:
    if cache is not None:
        await cache.delete(key)
        return
    _MEM.pop(key, None)


async def _claim(cache: Any, key: str, ttl: int) -> bool:
    """Atomically set ``key`` only if absent; True for exactly one caller."""
    if cache is not None:
        return bool(await cache.set_nx(key, "1", ttl))
    if _mem_get(key) is not None:
        return False
    _MEM[key] = (time.time() + ttl, "1")
    return True


class UserLockTimeout(Exception):
    """Another two-step operation for this user did not finish in time."""


@asynccontextmanager
async def user_lock(cache: Any, user_id: str):
    """Serialise every two-step write for one user across API processes.

    Callers re-read the user record inside the lock, so a recovery code or an
    authenticator time step is consumed exactly once even when requests overlap.
    """
    key = f"auth:mfa:lock:{user_id}"
    deadline = time.monotonic() + USER_LOCK_WAIT_SECONDS
    while not await _claim(cache, key, USER_LOCK_TTL_SECONDS):
        if time.monotonic() >= deadline:
            raise UserLockTimeout(user_id)
        await asyncio.sleep(_USER_LOCK_POLL_SECONDS)
    try:
        yield
    finally:
        await _delete(cache, key)


def _challenge_key(token: str) -> str:
    return f"auth:mfa:challenge:{hashlib.sha256(token.encode()).hexdigest()}"


def _consumed_key(token: str) -> str:
    return f"auth:mfa:consumed:{hashlib.sha256(token.encode()).hexdigest()}"


async def create_challenge(cache: Any, *, tenant_id: str, user_id: str, method: str,
                           plan_tier: str = "") -> str:
    token = secrets.token_urlsafe(32)
    await _put(cache, _challenge_key(token), {
        "tenant_id": tenant_id, "user_id": user_id, "method": method,
        "plan_tier": plan_tier, "attempts": 0,
    }, CHALLENGE_TTL_SECONDS)
    return token


async def load_challenge(cache: Any, token: str) -> Optional[dict]:
    return await _get(cache, _challenge_key(token))


async def record_failed_attempt(cache: Any, token: str, challenge: dict) -> bool:
    """Count a wrong code; return False once the challenge is exhausted (and drop it)."""
    challenge = {**challenge, "attempts": int(challenge.get("attempts", 0)) + 1}
    if challenge["attempts"] >= CHALLENGE_MAX_ATTEMPTS:
        await _delete(cache, _challenge_key(token))
        return False
    await _put(cache, _challenge_key(token), challenge, CHALLENGE_TTL_SECONDS)
    return True


async def consume_challenge(cache: Any, token: str) -> bool:
    """Spend a challenge; True only for the one request that wins it."""
    if not await _claim(cache, _consumed_key(token), CHALLENGE_TTL_SECONDS):
        return False
    await _delete(cache, _challenge_key(token))
    return True


async def drop_challenge(cache: Any, token: str) -> None:
    await _delete(cache, _challenge_key(token))


def _pending_key(user_id: str) -> str:
    return f"auth:mfa:pending:{user_id}"


async def stash_pending_enrolment(cache: Any, user_id: str, sealed_secret: str) -> None:
    await _put(cache, _pending_key(user_id), {"secret": sealed_secret}, PENDING_ENROLMENT_TTL_SECONDS)


async def take_pending_enrolment(cache: Any, user_id: str) -> Optional[str]:
    value = await _get(cache, _pending_key(user_id))
    return value.get("secret") if value else None


async def clear_pending_enrolment(cache: Any, user_id: str) -> None:
    await _delete(cache, _pending_key(user_id))


def is_enabled(user: Optional[dict]) -> bool:
    return bool(user and user.get("mfa_enabled") and user.get("mfa_totp_secret"))
