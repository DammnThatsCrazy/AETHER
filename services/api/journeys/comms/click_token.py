"""Signed post-click correlation token (Phase 11).

Links append an opaque signed token: ``https://tenant.example/path?ae=<token>``.
On landing, the SDK forwards the token as acquisition evidence; the backend
verifies the signature, validates tenant and expiry, and correlates the
anonymous session to (campaign, message, link, recipient alias).

Token format: ``v<version>.<payload-b64url>.<sig-b64url>`` where the payload
is compact JSON with short keys:

    t  tenant_id           c  canonical campaign_id
    m  external_message_id r  recipient_alias_id (tenant-scoped hash)
    l  link_id             s  sequence_step
    e  expiry (unix)       n  nonce

Contains no raw email addresses, no PII, no provider secrets (ADR-C10).
Key rotation: COMMS_CLICK_TOKEN_KEYS holds ``version:secret`` pairs separated
by commas; COMMS_CLICK_TOKEN_ACTIVE_VERSION selects the signing key while all
listed versions remain valid for verification.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.comms.click_token")

DEFAULT_TTL_SECONDS = 30 * 24 * 3600  # 30 days — email links live long

_DEV_KEY = "aether-dev-click-token-key"


def _keys() -> dict[str, bytes]:
    raw = os.getenv("COMMS_CLICK_TOKEN_KEYS", "")
    if not raw:
        return {"1": _DEV_KEY.encode()}
    keys: dict[str, bytes] = {}
    for pair in raw.split(","):
        version, _, secret = pair.strip().partition(":")
        if version and secret:
            keys[version] = secret.encode()
    return keys or {"1": _DEV_KEY.encode()}


def _active_version() -> str:
    version = os.getenv("COMMS_CLICK_TOKEN_ACTIVE_VERSION", "")
    keys = _keys()
    if version in keys:
        return version
    return sorted(keys)[-1]


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64d(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _sign(version: str, payload_b64: str) -> str:
    key = _keys()[version]
    return _b64e(hmac.new(key, f"v{version}.{payload_b64}".encode(), hashlib.sha256).digest())


@dataclass
class ClickTokenClaims:
    tenant_id: str
    campaign_id: Optional[str]
    external_message_id: Optional[str]
    recipient_alias_id: Optional[str]
    link_id: Optional[str]
    sequence_step: Optional[int]
    expires_at: int
    nonce: str
    key_version: str


@dataclass
class ClickTokenVerification:
    valid: bool
    claims: Optional[ClickTokenClaims] = None
    error: Optional[str] = None  # invalid_format | invalid_signature | expired | tenant_mismatch


def issue_click_token(
    tenant_id: str,
    *,
    campaign_id: Optional[str] = None,
    external_message_id: Optional[str] = None,
    recipient_alias_id: Optional[str] = None,
    link_id: Optional[str] = None,
    sequence_step: Optional[int] = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> str:
    """Issue a signed correlation token for one (recipient, link) pair."""
    payload = {
        "t": tenant_id,
        "c": campaign_id,
        "m": external_message_id,
        "r": recipient_alias_id,
        "l": link_id,
        "s": sequence_step,
        "e": int(time.time()) + ttl_seconds,
        "n": uuid.uuid4().hex[:12],
    }
    compact = {k: v for k, v in payload.items() if v is not None}
    payload_b64 = _b64e(json.dumps(compact, separators=(",", ":"), sort_keys=True).encode())
    version = _active_version()
    return f"v{version}.{payload_b64}.{_sign(version, payload_b64)}"


def verify_click_token(token: str, expected_tenant_id: str) -> ClickTokenVerification:
    """Verify signature, expiry, and tenant ownership of a click token.

    Cross-tenant tokens are rejected even with a valid signature — a token
    minted for tenant A never correlates activity in tenant B.
    """
    try:
        version_part, payload_b64, sig = token.split(".", 2)
        if not version_part.startswith("v"):
            raise ValueError("missing version prefix")
        version = version_part[1:]
    except (ValueError, AttributeError):
        metrics.increment("comms_click_token_invalid_total", labels={"reason": "format"})
        return ClickTokenVerification(valid=False, error="invalid_format")

    keys = _keys()
    if version not in keys:
        metrics.increment("comms_click_token_invalid_total", labels={"reason": "unknown_key_version"})
        return ClickTokenVerification(valid=False, error="invalid_signature")

    expected_sig = _sign(version, payload_b64)
    if not hmac.compare_digest(expected_sig, sig):
        metrics.increment("comms_click_token_invalid_total", labels={"reason": "signature"})
        return ClickTokenVerification(valid=False, error="invalid_signature")

    try:
        payload = json.loads(_b64d(payload_b64))
    except (ValueError, json.JSONDecodeError):
        metrics.increment("comms_click_token_invalid_total", labels={"reason": "payload"})
        return ClickTokenVerification(valid=False, error="invalid_format")

    claims = ClickTokenClaims(
        tenant_id=str(payload.get("t", "")),
        campaign_id=payload.get("c"),
        external_message_id=payload.get("m"),
        recipient_alias_id=payload.get("r"),
        link_id=payload.get("l"),
        sequence_step=payload.get("s"),
        expires_at=int(payload.get("e", 0)),
        nonce=str(payload.get("n", "")),
        key_version=version,
    )

    if claims.expires_at < time.time():
        metrics.increment("comms_click_token_invalid_total", labels={"reason": "expired"})
        return ClickTokenVerification(valid=False, claims=claims, error="expired")

    if claims.tenant_id != expected_tenant_id:
        metrics.increment("comms_click_token_invalid_total", labels={"reason": "tenant_mismatch"})
        return ClickTokenVerification(valid=False, error="tenant_mismatch")

    return ClickTokenVerification(valid=True, claims=claims)


# Campaign evidence priority when several sources disagree (Phase 11).
# Lower number wins; consumed by the campaign resolver call sites.
CAMPAIGN_EVIDENCE_PRIORITY: dict[str, int] = {
    "signed_click_token": 1,
    "provider_click_id": 2,
    "utm_id": 3,
    "external_campaign_id": 4,
    "utm_campaign_composite": 5,
    "referrer_landing": 6,
    "manual_review": 7,
}


def correlation_evidence_from_token(
    token: str, tenant_id: str,
) -> Optional[dict[str, Any]]:
    """Verified token → acquisitionEvidence-shaped campaign/identity evidence.

    Used by the landing/session path: the returned dict merges into the
    touchpoint's acquisition evidence and, when the alias is present and
    permitted, feeds identity resolution with 'signed_click' confidence.
    """
    result = verify_click_token(token, tenant_id)
    if not result.valid or result.claims is None:
        return None
    claims = result.claims
    return {
        "canonicalCampaignId": claims.campaign_id,
        "externalMessageId": claims.external_message_id,
        "recipientAliasId": claims.recipient_alias_id,
        "linkId": claims.link_id,
        "sequenceStep": claims.sequence_step,
        "evidence_source": "signed_click_token",
        "evidence_priority": CAMPAIGN_EVIDENCE_PRIORITY["signed_click_token"],
        "identity_method": "signed_click",
    }
