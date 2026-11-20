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
# Landing-side correlation
# =============================================================================
#
# Flow for a visit that lands with ``?ae=<token>``:
#
# 1. The SDK forwards the token as ``context.trafficSource.clickToken``.
# 2. At the authenticated ingestion boundary (``build_normalized_payload``),
#    :func:`seal_click_token_in_payload` verifies the token for the request's
#    tenant, removes it from every field and URL, and attaches a seal bound to
#    that one event (``verified_click``). The reusable link token is therefore
#    never persisted to Bronze or the outbox; a stored seal cannot be replayed
#    onto another event.
# 3. The Silver dispatcher (:func:`resolve_click_correlation`) and the identity
#    worker (:func:`identity_signals_for_click`) open the seal and call
#    :func:`evaluate_click_recipient`, which applies consent, first-device
#    binding and the forwarded-link rule identically for both consumers.

CLICK_TOKEN_QUERY_PARAM = "ae"
CLICK_SEAL_FIELD = "verified_click"

# The query parameter is short and generic, so a value is treated as an Aether
# click token only when it has the signed ``v<ver>.<payload>.<sig>`` shape.
_TOKEN_SHAPE = re.compile(r"^v[0-9A-Za-z]{1,16}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{16,}$")
_ALIAS_SHAPE = re.compile(r"^[0-9a-f]{64}$")

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
    ("deepLink", "url"),
)
_CLICK_PROP_URL_FIELDS = ("landing_url", "landingUrl", "url", "deep_link", "deepLink")


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


def _extract_and_strip(ctx: dict[str, Any], props: dict[str, Any]) -> Optional[str]:
    """Pop the token from typed fields and URLs of one context/properties pair."""
    token: Optional[str] = None
    for mapping in (ctx.get("acquisitionEvidence"), ctx.get("trafficSource"), ctx, props):
        if not isinstance(mapping, dict):
            continue
        for key in list(mapping):
            normalized = _field_key(key)
            if normalized in _CLICK_TOKEN_FIELD_KEYS:
                candidate = mapping.pop(key, None)
                if token is None and looks_like_click_token(candidate):
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


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def extract_and_strip_click_token(event: dict[str, Any]) -> Optional[str]:
    """Pop the click token from an SDK-envelope event; drop forged claims.

    Always mutates ``event`` so neither the plaintext token nor a
    client-asserted correlation result reaches Silver.
    """
    event.pop("_verified_click", None)
    return _extract_and_strip(_dict(event.get("context")), _dict(event.get("properties")))


# ── Event-bound seal ─────────────────────────────────────────────────────────

def _seal_mac(version: str, tenant_id: str, event_id: str, payload_b64: str) -> str:
    key = _keys()[version]
    message = f"seal.v{version}.{tenant_id}.{event_id}.{payload_b64}".encode()
    return _b64e(hmac.new(key, message, hashlib.sha256).digest())


def seal_click_claims(claims: ClickTokenClaims, tenant_id: str, event_id: str) -> dict[str, str]:
    """Bind verified claims to one (tenant, event) so a stored copy cannot be replayed."""
    body = {
        "c": claims.campaign_id, "m": claims.external_message_id,
        "r": claims.recipient_alias_id, "l": claims.link_id,
        "s": claims.sequence_step, "e": claims.expires_at,
        "n": claims.nonce, "k": claims.key_version,
    }
    compact = {k: v for k, v in body.items() if v is not None}
    payload_b64 = _b64e(json.dumps(compact, separators=(",", ":"), sort_keys=True).encode())
    version = _active_version()
    return {"v": version, "p": payload_b64, "sig": _seal_mac(version, tenant_id, event_id, payload_b64)}


def open_click_seal(sealed: Any, tenant_id: str, event_id: str) -> Optional[ClickTokenClaims]:
    """Return the sealed claims only when the seal matches this tenant and event."""
    if not isinstance(sealed, dict) or not tenant_id or not event_id:
        return None
    version, payload_b64, sig = (str(sealed.get(k) or "") for k in ("v", "p", "sig"))
    if not version or not payload_b64 or not sig or version not in _keys():
        metrics.increment("comms_click_seal_invalid_total", labels={"reason": "format"})
        return None
    if not hmac.compare_digest(_seal_mac(version, tenant_id, event_id, payload_b64), sig):
        metrics.increment("comms_click_seal_invalid_total", labels={"reason": "signature"})
        return None
    try:
        body = json.loads(_b64d(payload_b64))
    except (ValueError, json.JSONDecodeError):
        return None
    return ClickTokenClaims(
        tenant_id=tenant_id,
        campaign_id=body.get("c"),
        external_message_id=body.get("m"),
        recipient_alias_id=body.get("r"),
        link_id=body.get("l"),
        sequence_step=body.get("s"),
        expires_at=int(body.get("e", 0)),
        nonce=str(body.get("n", "")),
        key_version=str(body.get("k", "")),
    )


def seal_click_token_in_payload(payload: dict[str, Any]) -> None:
    """Ingestion boundary: verify the token, strip it, attach an event-bound seal.

    ``payload`` is the normalized bus payload whose ``tenant_id`` comes from
    the authenticated request. Any incoming ``verified_click`` is discarded
    first, so only this function can attach one.
    """
    payload.pop(CLICK_SEAL_FIELD, None)
    token = _extract_and_strip(_dict(payload.get("context")), _dict(payload.get("properties")))
    if not token:
        return
    tenant_id = str(payload.get("tenant_id") or "")
    event_id = str(payload.get("event_id") or "")
    result = verify_click_token(token, tenant_id)
    if not result.valid or result.claims is None or not event_id:
        metrics.increment(
            "comms_click_correlation_total", labels={"status": result.error or "invalid"}
        )
        return
    payload[CLICK_SEAL_FIELD] = seal_click_claims(result.claims, tenant_id, event_id)


def scrub_click_token(mapping: Any) -> Any:
    """Defense in depth for persistence: drop any raw click token left anywhere."""
    if isinstance(mapping, dict):
        for key in list(mapping):
            if _field_key(key) in _CLICK_TOKEN_FIELD_KEYS:
                mapping.pop(key, None)
            else:
                mapping[key] = scrub_click_token(mapping[key])
        return mapping
    if isinstance(mapping, list):
        return [scrub_click_token(item) for item in mapping]
    if isinstance(mapping, str) and f"{CLICK_TOKEN_QUERY_PARAM}=" in mapping:
        return strip_click_token_from_url(mapping)
    return mapping


# ── Recipient decision (shared by Silver and identity) ──────────────────────

@dataclass
class ClickRecipientDecision:
    outcome: str  # resolved | forwarded | unresolved | absent | consent_required | binding_unavailable
    recipient_entity_id: Optional[str] = None
    identity_method: Optional[str] = None
    identity_confidence: Optional[float] = None

    @property
    def may_link_identity(self) -> bool:
        """True when this visitor may be linked to the recipient's email alias."""
        return self.outcome in {"resolved", "unresolved"}


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def claim_first_device(
    tenant_id: str, claims: ClickTokenClaims, visitor_key: str, *, cache: Any = None,
) -> bool:
    """Bind a token to the first visitor that presents it (idempotent per visitor).

    The binding stores only hashes and lives as long as the token. Raises when
    the cache is unavailable so callers can fail closed.
    """
    if cache is None:
        from dependencies.providers import get_cache

        cache = get_cache()
    key = "aether:comms:click_bind:" + _sha(
        f"{tenant_id}|{claims.nonce}|{claims.recipient_alias_id}|{claims.link_id}"
    )
    mine = _sha(f"{tenant_id}|{visitor_key}")
    ttl = max(60, int(claims.expires_at - time.time()))
    if await cache.set_nx(key, mine, ttl=ttl):
        return True
    return (await cache.get(key)) == mine


async def _session_subject_entity(
    tenant_id: str, user_id: str, anonymous_id: str, namespace: str,
) -> Optional[str]:
    """Canonical entity already bound to this visitor (user id, else anon id)."""
    from identity.identity.models import IdentitySignalType
    from identity.identity.normalization import normalize_anonymous_id, normalize_user_id
    from journeys.comms.identity_bridge import resolve_unique_tenant_entity_for_alias

    if user_id:
        scoped = f"{namespace}:{user_id}" if namespace else user_id
        entity = await resolve_unique_tenant_entity_for_alias(
            tenant_id, IdentitySignalType.USER_ID, normalize_user_id(scoped, tenant_id)
        )
        if entity:
            return entity
    if anonymous_id:
        return await resolve_unique_tenant_entity_for_alias(
            tenant_id,
            IdentitySignalType.ANONYMOUS_ID,
            normalize_anonymous_id(anonymous_id, tenant_id),
        )
    return None


async def evaluate_click_recipient(
    claims: ClickTokenClaims,
    *,
    tenant_id: str,
    user_id: str = "",
    anonymous_id: str = "",
    identity_namespace: str = "",
    consent_snapshot: Any = None,
    cache: Any = None,
) -> ClickRecipientDecision:
    """Decide whether this visitor is the token's recipient.

    * no recipient alias → ``absent``;
    * no identity-stitching consent on the event → ``consent_required``
      (the same rule the identity resolver applies to email hashes);
    * another visitor already presented this token first → ``forwarded``;
    * the visitor is already a different known entity → ``forwarded``;
    * the alias maps to exactly one tenant-owned entity → ``resolved``;
    * otherwise → ``unresolved`` (identity may still link the alias).
    """
    from identity.identity.confidence import has_stitching_consent
    from identity.identity.models import IdentitySignalType
    from journeys.comms.identity_bridge import resolve_unique_tenant_entity_for_alias
    from journeys.comms.mailbox import IDENTITY_METHOD_CONFIDENCE

    alias = claims.recipient_alias_id
    if not alias or not _ALIAS_SHAPE.match(alias):
        return ClickRecipientDecision("absent")
    if not has_stitching_consent(consent_snapshot if isinstance(consent_snapshot, dict) else None):
        return ClickRecipientDecision("consent_required")

    forwarded = ClickRecipientDecision(
        "forwarded", identity_method="forwarded_link",
        identity_confidence=IDENTITY_METHOD_CONFIDENCE["forwarded_link"],
    )
    visitor_key = anonymous_id or user_id
    if not visitor_key:
        return ClickRecipientDecision("binding_unavailable")
    try:
        if not await claim_first_device(tenant_id, claims, visitor_key, cache=cache):
            return forwarded
    except Exception as exc:  # fail closed: never attribute without the binding
        logger.warning("click_binding_unavailable tenant=%s: %s", tenant_id, exc)
        return ClickRecipientDecision("binding_unavailable")

    recipient = await resolve_unique_tenant_entity_for_alias(
        tenant_id, IdentitySignalType.EMAIL_HASH, alias
    )
    session_entity = await _session_subject_entity(
        tenant_id, user_id, anonymous_id, identity_namespace
    )
    if session_entity and session_entity != recipient:
        return forwarded
    if recipient is None:
        return ClickRecipientDecision("unresolved")
    return ClickRecipientDecision(
        "resolved", recipient_entity_id=recipient, identity_method="signed_click",
        identity_confidence=IDENTITY_METHOD_CONFIDENCE["signed_click"],
    )


# ── Silver dispatcher ────────────────────────────────────────────────────────

def _event_tenant_id(event: dict[str, Any]) -> str:
    ctx = _dict(event.get("context"))
    return str(ctx.get("tenantId") or event.get("tenantId") or "default")


def _event_claims(event: dict[str, Any], tenant_id: str) -> Optional[ClickTokenClaims]:
    """Sealed claims from ingestion, else a raw token (non-boundary callers)."""
    sealed = event.pop(CLICK_SEAL_FIELD, None)
    token = extract_and_strip_click_token(event)
    event_id = str(event.get("messageId") or event.get("id") or "")
    if sealed is not None:
        return open_click_seal(sealed, tenant_id, event_id)
    if not token:
        return None
    result = verify_click_token(token, tenant_id)
    if not result.valid:
        metrics.increment(
            "comms_click_correlation_total", labels={"status": result.error or "invalid"}
        )
        return None
    return result.claims


async def resolve_click_correlation(event: dict[str, Any], *, cache: Any = None) -> None:
    """Attach a server-derived ``_verified_click`` claim to an SDK-envelope event."""
    tenant_id = _event_tenant_id(event)
    claims = _event_claims(event, tenant_id)
    if claims is None:
        return
    ctx = _dict(event.get("context"))
    decision = await evaluate_click_recipient(
        claims,
        tenant_id=tenant_id,
        user_id=str(event.get("userId") or event.get("user_id") or "").strip(),
        anonymous_id=str(event.get("anonymousId") or event.get("anonymous_id") or "").strip(),
        identity_namespace=str(ctx.get("identity_namespace") or ctx.get("identityNamespace") or "").strip(),
        consent_snapshot=ctx.get("consent"),
        cache=cache,
    )
    event["_verified_click"] = {
        "campaign_id": claims.campaign_id,
        "external_message_id": claims.external_message_id,
        "link_id": claims.link_id,
        "sequence_step": claims.sequence_step,
        "key_version": claims.key_version,
        "recipient_outcome": decision.outcome,
        "recipient_entity_id": decision.recipient_entity_id,
        "identity_method": decision.identity_method,
        "identity_confidence": decision.identity_confidence,
    }
    metrics.increment("comms_click_correlation_total", labels={"status": decision.outcome})


def strip_click_correlation(event: dict[str, Any]) -> None:
    """Sync/compat path: remove the seal and any raw token without resolving."""
    event.pop(CLICK_SEAL_FIELD, None)
    extract_and_strip_click_token(event)


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


# ── Identity worker ──────────────────────────────────────────────────────────

async def identity_signals_for_click(
    payload: dict[str, Any], *, tenant_id: str, cache: Any = None,
) -> list[dict[str, str]]:
    """Server-only resolver signals for a sealed click on a normalized payload.

    Returns the recipient's tenant-scoped email hash when the visitor may be
    linked to it (consented, first device, not already a different person).
    The resolver then links the visitor to the recipient, or creates an entity
    holding the alias that later merges when the person signs up.
    """
    claims = open_click_seal(
        payload.get(CLICK_SEAL_FIELD), tenant_id, str(payload.get("event_id") or "")
    )
    if claims is None:
        return []
    ctx = _dict(payload.get("context"))
    decision = await evaluate_click_recipient(
        claims,
        tenant_id=tenant_id,
        user_id=str(payload.get("user_id") or "").strip(),
        anonymous_id=str(payload.get("anonymous_id") or "").strip(),
        identity_namespace=str(ctx.get("identity_namespace") or "").strip(),
        consent_snapshot=ctx.get("consent"),
        cache=cache,
    )
    if not decision.may_link_identity:
        return []
    return [{"type": "email_hash", "hash": str(claims.recipient_alias_id), "source": "signed_click"}]
