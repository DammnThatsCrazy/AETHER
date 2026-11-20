"""Device integrity routes: single-use challenge, then attestation verify.

POST /sdk/device-integrity/challenge  {platform, anonymousId}
POST /sdk/device-integrity/verify     {platform, anonymousId, challenge,
                                       keyId + attestationObject (ios) |
                                       integrityToken (android)}

Callable with the mobile SDK's ingest credential (see middleware). The verify
response carries a short-lived integrity token for ``context.device.integrity``.
"""

from __future__ import annotations

import json
import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from config.settings import Environment, settings
from dependencies.providers import get_cache
from shared.cache.cache import CacheClient
from shared.logger.logger import get_logger, metrics

from ingestion.device_integrity import tokens

logger = get_logger("aether.device_integrity")
router = APIRouter(prefix="/sdk/device-integrity", tags=["SDK"])

_CHALLENGE_KEY = "device_integrity:challenge:{}"


class ChallengeRequest(BaseModel):
    platform: str = Field(pattern="^(ios|android)$")
    anonymousId: str = Field(min_length=1, max_length=256)


class VerifyRequest(BaseModel):
    platform: str = Field(pattern="^(ios|android)$")
    anonymousId: str = Field(min_length=1, max_length=256)
    challenge: str = Field(min_length=16, max_length=128)
    keyId: Optional[str] = Field(default=None, max_length=256)
    attestationObject: Optional[str] = Field(default=None, max_length=64_000)
    integrityToken: Optional[str] = Field(default=None, max_length=16_000)
    packageName: Optional[str] = Field(default=None, max_length=256)


def _error(code: str, status: int = 400) -> Any:
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=status, content={"ok": False, "error": code})


def _key() -> Optional[bytes]:
    cfg = settings.device_integrity
    return tokens.token_key(cfg.token_secret, allow_ephemeral=settings.env == Environment.LOCAL)


@router.post("/challenge")
async def issue_challenge(body: ChallengeRequest, request: Request, cache: CacheClient = Depends(get_cache)):
    cfg = settings.device_integrity
    if not cfg.enabled:
        return _error("device_integrity_disabled", 404)
    if _key() is None:
        return _error("device_integrity_not_configured", 503)
    tenant_id = str(request.state.tenant.tenant_id)
    challenge = tokens.new_challenge()
    record = {"t": tenant_id, "p": body.platform, "a": body.anonymousId, "iat_ms": int(time.time() * 1000)}
    await cache.set(_CHALLENGE_KEY.format(challenge), json.dumps(record), ttl=cfg.challenge_ttl_seconds)
    return {"ok": True, "challenge": challenge, "expiresInSeconds": cfg.challenge_ttl_seconds}


async def _consume_challenge(cache: CacheClient, challenge: str) -> Optional[dict[str, Any]]:
    key = _CHALLENGE_KEY.format(challenge)
    raw = await cache.get(key)
    if raw is None:
        return None
    # Single use: the first verify to claim it wins, any replay is refused.
    if not await cache.set_nx(key + ":used", "1", ttl=settings.device_integrity.challenge_ttl_seconds):
        return None
    await cache.delete(key)
    try:
        return json.loads(raw)
    except ValueError:
        return None


async def _verify_ios(cfg, body: VerifyRequest) -> tuple[str, str]:
    from ingestion.device_integrity.app_attest import AppAttestError, verify_attestation

    if not cfg.apple_app_ids:
        raise LookupError("app_attest_not_configured")
    if not body.keyId or not body.attestationObject:
        raise ValueError("ios_attestation_missing")
    try:
        verify_attestation(
            key_id_b64=body.keyId, attestation_object_b64=body.attestationObject, challenge=body.challenge,
            app_ids=cfg.apple_app_ids, environment=cfg.apple_environment,
        )
        return "verified", "app_attest_valid"
    except AppAttestError as exc:
        return "failed", exc.reason


async def _verify_android(cfg, body: VerifyRequest, issued_at_ms: int) -> tuple[str, str]:
    from ingestion.device_integrity.play_integrity import PlayIntegrityError, decode_token, evaluate_payload

    if not cfg.play_package_names or not cfg.play_service_account_json:
        raise LookupError("play_integrity_not_configured")
    if not body.integrityToken:
        raise ValueError("android_integrity_token_missing")
    package = body.packageName if body.packageName in cfg.play_package_names else cfg.play_package_names[0]
    try:
        payload = await decode_token(body.integrityToken, package, cfg.play_service_account_json)
        result = evaluate_payload(
            payload, challenge=body.challenge, allowed_packages=cfg.play_package_names,
            certificate_digests=cfg.play_certificate_digests, issued_at_ms=issued_at_ms,
            max_age_ms=cfg.challenge_ttl_seconds * 1000,
        )
        return result.verdict, ",".join(result.reasons) or "play_integrity_valid"
    except PlayIntegrityError as exc:
        if exc.reason in ("google_auth_failed", "service_account_invalid", "decode_failed"):
            raise LookupError(exc.reason) from exc
        return "failed", exc.reason


@router.post("/verify")
async def verify(body: VerifyRequest, request: Request, cache: CacheClient = Depends(get_cache)):
    cfg = settings.device_integrity
    if not cfg.enabled:
        return _error("device_integrity_disabled", 404)
    key = _key()
    if key is None:
        return _error("device_integrity_not_configured", 503)
    tenant_id = str(request.state.tenant.tenant_id)
    record = await _consume_challenge(cache, body.challenge)
    if record is None:
        return _error("challenge_unknown_or_used")
    if record.get("t") != tenant_id or record.get("p") != body.platform or record.get("a") != body.anonymousId:
        return _error("challenge_mismatch")
    try:
        if body.platform == "ios":
            verdict, reason = await _verify_ios(cfg, body)
        else:
            verdict, reason = await _verify_android(cfg, body, int(record.get("iat_ms") or 0))
    except LookupError as exc:
        return _error(str(exc), 503)
    except ValueError as exc:
        return _error(str(exc))
    token, expires = tokens.issue_token(
        key, tenant_id=tenant_id, anonymous_id=body.anonymousId, platform=body.platform,
        verdict=verdict, ttl_seconds=cfg.token_ttl_hours * 3600,
    )
    metrics.increment("device_integrity_verdict_total", labels={"platform": body.platform, "verdict": verdict})
    logger.info("device_integrity verdict platform=%s verdict=%s reason=%s", body.platform, verdict, reason)
    return {"ok": True, "verdict": verdict, "reason": reason, "integrityToken": token, "expiresAt": expires}


__all__ = ["router"]
