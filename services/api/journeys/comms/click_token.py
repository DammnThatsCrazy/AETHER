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
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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


# =============================================================================
# Landing-side correlation (Silver ingestion)
# =============================================================================
#
# The SDK forwards the ``ae`` link parameter as ``clickToken`` in the
# acquisition evidence. The Silver dispatcher calls
# :func:`resolve_click_correlation` before any touchpoint is projected and
# :func:`apply_click_correlation_to_rows` before campaign resolution. Only a
# token that verifies for the event's own tenant ever influences a row; the
# plaintext token is removed from the event either way, and client-asserted
# correlation claims are discarded.

CLICK_TOKEN_QUERY_PARAM = "ae"

# The query parameter is short and generic, so a value is treated as an Aether
# click token only when it has the signed ``v<ver>.<payload>.<sig>`` shape.
_TOKEN_SHAPE = re.compile(r"^v[0-9A-Za-z]{1,16}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{16,}$")

_CLICK_TOKEN_FIELD_KEYS = frozenset({"click_token", "clicktoken"})
# Correlation outcomes are server-derived only; the SDK cannot assert them.
_UNTRUSTED_CLICK_CLAIM_KEYS = frozenset({
    "verified_click", "verifiedclick", "verified_click_token", "verifiedclicktoken",
    "_verified_click",
})
_CLICK_URL_FIELDS: tuple[tuple[str, str], ...] = (
    ("page", "url"),
    ("page", "search"),
    ("acquisitionEvidence", "landingPage"),
    ("acquisitionEvidence", "landing_page"),
    ("trafficSource", "landingPage"),
    ("trafficSource", "landing_page"),
)
_CLICK_PROP_URL_FIELDS = ("landing_url", "landingUrl")


def _field_key(value: Any) -> str:
    return str(value).strip().replace("-", "_").lower()


def looks_like_click_token(value: Any) -> bool:
    return isinstance(value, str) and bool(_TOKEN_SHAPE.match(value))


def _click_token_from_url(value: Any) -> Optional[str]:
    if not isinstance(value, str) or not value:
        return None
    try:
        query = value[1:] if value.startswith("?") else urlsplit(value).query
        for key, item in parse_qsl(query, keep_blank_values=True):
            if key == CLICK_TOKEN_QUERY_PARAM and looks_like_click_token(item):
                return item
    except (TypeError, ValueError):
        return None
    return None


def strip_click_token_from_url(value: Any) -> Any:
    """Remove a token-shaped ``ae`` parameter; keep every other parameter."""
    if not isinstance(value, str) or not value:
        return value
    try:
        is_search = value.startswith("?")
        parsed = urlsplit(value[1:] if is_search else value)
        query = value[1:] if is_search else parsed.query
        pairs = parse_qsl(query, keep_blank_values=True)
        kept = [
            (k, v) for k, v in pairs
            if not (k == CLICK_TOKEN_QUERY_PARAM and looks_like_click_token(v))
        ]
        if len(kept) == len(pairs):
            return value
        encoded = urlencode(kept, doseq=True)
        if is_search:
            return f"?{encoded}" if encoded else ""
        return urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, encoded, parsed.fragment)
        )
    except (TypeError, ValueError):
        return value


def extract_and_strip_click_token(event: dict[str, Any]) -> Optional[str]:
    """Pop the click token from typed fields and URLs; drop forged claims.

    Always mutates ``event`` so neither the plaintext token nor a
    client-asserted correlation result reaches Silver, even when the token
    later fails verification.
    """
    event.pop("_verified_click", None)
    ctx = event.get("context") if isinstance(event.get("context"), dict) else {}
    props = event.get("properties") if isinstance(event.get("properties"), dict) else {}
    containers = [
        ctx.get("acquisitionEvidence"),
        ctx.get("trafficSource"),
        ctx,
        props,
    ]
    token: Optional[str] = None
    for mapping in containers:
        if not isinstance(mapping, dict):
            continue
        for key in list(mapping):
            normalized = _field_key(key)
            if normalized in _CLICK_TOKEN_FIELD_KEYS:
                candidate = mapping.pop(key, None)
                if token is None and isinstance(candidate, str) and candidate:
                    token = candidate
            elif normalized in _UNTRUSTED_CLICK_CLAIM_KEYS:
                mapping.pop(key, None)

    url_slots: list[tuple[dict[str, Any], str]] = []
    for container_key, field_name in _CLICK_URL_FIELDS:
        container = ctx.get(container_key)
        if isinstance(container, dict) and field_name in container:
            url_slots.append((container, field_name))
    for field_name in _CLICK_PROP_URL_FIELDS:
        if field_name in props:
            url_slots.append((props, field_name))
    for mapping, field_name in url_slots:
        raw = mapping.get(field_name)
        token = token or _click_token_from_url(raw)
        mapping[field_name] = strip_click_token_from_url(raw)
    return token


def _event_tenant_id(event: dict[str, Any]) -> str:
    ctx = event.get("context") if isinstance(event.get("context"), dict) else {}
    return str(ctx.get("tenantId") or event.get("tenantId") or "default")


async def _session_subject_entity(event: dict[str, Any], tenant_id: str) -> Optional[str]:
    """Canonical entity already bound to this visitor (user id, else anon id)."""
    from identity.identity.models import IdentitySignalType
    from identity.identity.normalization import normalize_anonymous_id, normalize_user_id
    from journeys.comms.identity_bridge import resolve_unique_tenant_entity_for_alias

    ctx = event.get("context") if isinstance(event.get("context"), dict) else {}
    user_id = str(event.get("userId") or event.get("user_id") or "").strip()
    if user_id:
        namespace = str(
            ctx.get("identity_namespace") or ctx.get("identityNamespace") or ""
        ).strip()
        scoped = f"{namespace}:{user_id}" if namespace else user_id
        entity = await resolve_unique_tenant_entity_for_alias(
            tenant_id, IdentitySignalType.USER_ID, normalize_user_id(scoped, tenant_id)
        )
        if entity:
            return entity
    anon_id = str(event.get("anonymousId") or event.get("anonymous_id") or "").strip()
    if anon_id:
        return await resolve_unique_tenant_entity_for_alias(
            tenant_id,
            IdentitySignalType.ANONYMOUS_ID,
            normalize_anonymous_id(anon_id, tenant_id),
        )
    return None


async def resolve_click_correlation(event: dict[str, Any]) -> None:
    """Verify the event's click token and attach a server-derived claim.

    On success sets ``event['_verified_click']`` with the campaign lineage and
    the recipient outcome:

    * ``resolved``   — the recipient alias maps to exactly one tenant entity
      and the visitor is not already bound to a different entity;
    * ``forwarded``  — the visitor is already bound to a different entity, so
      the link most likely travelled (identity is never reassigned);
    * ``unresolved`` — the alias maps to no single entity yet;
    * ``absent``     — the token carries no recipient alias.
    """
    token = extract_and_strip_click_token(event)
    if not token:
        return
    tenant_id = _event_tenant_id(event)
    result = verify_click_token(token, tenant_id)
    if not result.valid or result.claims is None:
        metrics.increment(
            "comms_click_correlation_total", labels={"status": result.error or "invalid"}
        )
        return
    claims = result.claims

    from identity.identity.models import IdentitySignalType
    from journeys.comms.identity_bridge import resolve_unique_tenant_entity_for_alias
    from journeys.comms.mailbox import IDENTITY_METHOD_CONFIDENCE

    recipient_entity_id: Optional[str] = None
    method: Optional[str] = None
    confidence: Optional[float] = None
    if not claims.recipient_alias_id:
        outcome = "absent"
    else:
        recipient_entity_id = await resolve_unique_tenant_entity_for_alias(
            tenant_id, IdentitySignalType.EMAIL_HASH, claims.recipient_alias_id
        )
        if recipient_entity_id is None:
            outcome = "unresolved"
        else:
            session_entity = await _session_subject_entity(event, tenant_id)
            if session_entity and session_entity != recipient_entity_id:
                outcome = "forwarded"
                method = "forwarded_link"
            else:
                outcome = "resolved"
                method = "signed_click"
            confidence = IDENTITY_METHOD_CONFIDENCE[method]

    event["_verified_click"] = {
        "campaign_id": claims.campaign_id,
        "external_message_id": claims.external_message_id,
        "link_id": claims.link_id,
        "sequence_step": claims.sequence_step,
        "key_version": claims.key_version,
        "recipient_outcome": outcome,
        "recipient_entity_id": recipient_entity_id if outcome == "resolved" else None,
        "identity_method": method,
        "identity_confidence": confidence,
    }
    metrics.increment("comms_click_correlation_total", labels={"status": outcome})


def apply_click_correlation_to_rows(
    rows: list[dict[str, Any]], event: dict[str, Any]
) -> None:
    """Stamp verified click lineage and recipient identity onto touchpoint rows.

    The signed token is the highest-priority campaign evidence
    (``CAMPAIGN_EVIDENCE_PRIORITY``), so its campaign hint replaces weaker
    hints; CampaignResolver still validates tenant ownership of the UUID.
    An identity already on the row is never overwritten.
    """
    claim = event.get("_verified_click")
    if not isinstance(claim, dict):
        return
    for row in rows:
        if claim.get("campaign_id"):
            row["_canonical_campaign_id_hint"] = claim["campaign_id"]
        for key in ("external_message_id", "link_id", "sequence_step"):
            if claim.get(key) is not None and row.get(key) is None:
                row[key] = claim[key]
        recipient = claim.get("recipient_entity_id")
        if recipient and not row.get("profile_id"):
            row["profile_id"] = recipient
        if claim.get("identity_method"):
            row["identity_resolution_method"] = claim["identity_method"]
            row["identity_confidence"] = claim["identity_confidence"]
        provenance = row.get("provenance")
        if isinstance(provenance, dict):
            provenance["click_correlation"] = {
                "evidence_source": "signed_click_token",
                "key_version": claim.get("key_version"),
                "recipient_outcome": claim.get("recipient_outcome"),
            }
