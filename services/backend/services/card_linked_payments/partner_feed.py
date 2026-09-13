"""Versioned, SIGNED card-linked partner-feed contract.

A GOVERNED inbound feed — NOT a generic arbitrary webhook. Every inbound
partner event is:

1. HMAC-SHA256 verified (constant-time compare) with a per-tenant partner
   secret resolved through the BYOK vault (``shared.providers.key_vault``),
   reusing the HMAC scheme from
   ``services.integrations.providers.payment_rails.base.PaymentRailAdapter``;
2. schema-versioned (``card_linked.partner_feed.v1``);
3. checked against a STRICT allowed-field allowlist — any blocked instrument /
   identity field (PAN, full card number, CVV, routing number, unmasked bank
   account, KYC/identity docs, secrets) is REJECTED with a precise reason, and
   any field outside the allowlist is REJECTED;
4. given a DETERMINISTIC idempotency key so exact redeliveries dedupe;
5. money-safe: amounts are validated as Decimal atomic strings, never floats.

Fail closed: outside ``AETHER_ENV=local`` an unsigned or invalid-signature
payload is rejected. In local mode a signature, when supplied, is still verified
(so tests exercise the real path); an absent signature is tolerated locally.

Aether OBSERVES this feed. The contract never executes, settles, or custodies.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timezone

from shared.temporal.instant import ensure_aware_utc
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from services.card_linked_payments.models import (
    CARD_LINKED_SCHEMA_VERSION,
    reject_blocked_fields,
)

# ── versioning ────────────────────────────────────────────────────────────────

CARD_LINKED_PARTNER_FEED_SCHEMA_VERSION = "card_linked.partner_feed.v1"
SUPPORTED_PARTNER_FEED_SCHEMA_VERSIONS = frozenset({
    CARD_LINKED_PARTNER_FEED_SCHEMA_VERSION,
})
# The underlying normalized-flow schema this feed maps onto.
CARD_LINKED_BASE_SCHEMA_VERSION = CARD_LINKED_SCHEMA_VERSION

# BYOK vault provider under which a tenant's partner-feed HMAC secret is stored.
# Scoped per partner as ``{PARTNER_FEED_VAULT_PROVIDER}:{partner}`` when a
# partner id is supplied, else the bare provider name.
PARTNER_FEED_VAULT_PROVIDER = "card_linked_partner_feed"

# HTTP headers the signed feed uses.
SIGNATURE_HEADER = "X-Aether-Partner-Signature"
TIMESTAMP_HEADER = "X-Aether-Partner-Timestamp"
PARTNER_HEADER = "X-Aether-Partner"
SCHEMA_VERSION_HEADER = "X-Aether-Feed-Version"

# ── strict allowlist ──────────────────────────────────────────────────────────
# ONLY these top-level fields may appear on a partner-feed event. Anything else
# (including — but not limited to — the hard-blocked instrument/identity fields)
# is rejected. Grouped for readability; the union is the effective allowlist.

_ALLOWED_ENVELOPE_FIELDS = frozenset({
    "schema_version", "partner", "provider", "provider_event_id",
    "event_id", "event_type", "id", "tenant_id",
})
_ALLOWED_TIME_FIELDS = frozenset({"event_time", "observed_time", "occurred_at"})
_ALLOWED_CLASSIFICATION_FIELDS = frozenset({
    "basis", "source_classification", "confidence", "region", "region_hint",
})
_ALLOWED_CONSENT_FIELDS = frozenset({
    "consent_snapshot", "consent_policy_decision_id", "policy_decision_ref",
})
_ALLOWED_PROGRAM_FIELDS = frozenset({
    "program", "program_id", "card_program_id", "issuer_id", "payment_network",
})
_ALLOWED_ONCHAIN_FIELDS = frozenset({"chain", "asset", "network"})
_ALLOWED_MONEY_FIELDS = frozenset({"amount_usd", "amount_native", "amount", "currency"})
# Pseudonymous / attributable identity. User-level fields are permitted here
# because ingestion's fail-closed consent + region gates govern them downstream;
# they are never trusted raw.
_ALLOWED_IDENTITY_FIELDS = frozenset({
    "wallet_address_hash", "provider_customer_ref", "actor_kind",
    "canonical_entity_id", "user_id", "agent_id", "org_id", "session_id", "device_id",
})
_ALLOWED_ATTRIBUTION_FIELDS = frozenset({"campaign_id", "journey_id"})
_ALLOWED_SEMANTICS_FIELDS = frozenset({
    "settlement_ref", "authorization_ref", "clearing_ref",
    "reversal_of", "refund_of", "evidence_refs", "masked_card_last4",
})

ALLOWED_PARTNER_FEED_FIELDS: frozenset[str] = (
    _ALLOWED_ENVELOPE_FIELDS
    | _ALLOWED_TIME_FIELDS
    | _ALLOWED_CLASSIFICATION_FIELDS
    | _ALLOWED_CONSENT_FIELDS
    | _ALLOWED_PROGRAM_FIELDS
    | _ALLOWED_ONCHAIN_FIELDS
    | _ALLOWED_MONEY_FIELDS
    | _ALLOWED_IDENTITY_FIELDS
    | _ALLOWED_ATTRIBUTION_FIELDS
    | _ALLOWED_SEMANTICS_FIELDS
)

# Money fields that must be atomic Decimal strings — never Python floats.
_MONEY_FIELDS = ("amount_usd", "amount_native", "amount")

# Partner-feed evidence is off-chain, spend-side ONLY. A partner may never claim
# top-up/funding (those are on-chain observations) — keeping top-up and spend
# structurally un-conflated at the feed boundary.
ALLOWED_PARTNER_FEED_BASES = frozenset({
    "spend", "settlement", "clearing", "refund", "reversal", "authorization",
})


# ── errors ────────────────────────────────────────────────────────────────────

class PartnerFeedError(ValueError):
    """Base class for partner-feed contract violations (maps to HTTP 422)."""


class PartnerFeedSignatureError(PartnerFeedError):
    """Unsigned or invalid-signature partner event (maps to HTTP 401)."""


class PartnerFeedSchemaError(PartnerFeedError):
    """Schema/allowlist/version/money violation (maps to HTTP 422)."""


def _is_local_env() -> bool:
    return os.getenv("AETHER_ENV", "local").lower() == "local"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── deterministic idempotency ─────────────────────────────────────────────────

def partner_feed_idempotency_key(tenant_id: str, partner: str, provider_event_id: str) -> str:
    """Deterministic, tenant + partner + event scoped key (schema-versioned).

    Exact redeliveries of the same event produce the same key, so ingestion's
    idempotent insert makes them structural no-ops.
    """
    return (
        f"{tenant_id}:partner_feed:{partner}:{provider_event_id}:"
        f"{CARD_LINKED_PARTNER_FEED_SCHEMA_VERSION}"
    )


# ── money / time coercion ─────────────────────────────────────────────────────

def _coerce_money(field: str, value: Any) -> Optional[str]:
    """Validate a money value as an atomic Decimal string; reject floats."""
    if value is None or value == "":
        return None
    if isinstance(value, float):
        raise PartnerFeedSchemaError(
            f"money field {field!r} must be an atomic string, not a float "
            "(float amounts are not exact)"
        )
    try:
        return str(Decimal(str(value)))
    except (InvalidOperation, ValueError) as exc:
        raise PartnerFeedSchemaError(
            f"money field {field!r} is not a valid decimal amount: {value!r}"
        ) from exc


def _to_utc_iso(field: str, value: Any) -> str:
    """Parse an ISO-8601 string (Z accepted) into a UTC ISO string."""
    text = str(value).strip()
    iso = text[:-1] + "+00:00" if text[-1:] in ("Z", "z") else text
    try:
        # ensure_aware_utc rejects timezone-naive input (TemporalError <: ValueError);
        # partner feeds must carry an explicit UTC offset (Z is normalized above).
        dt = ensure_aware_utc(datetime.fromisoformat(iso))
    except ValueError as exc:
        raise PartnerFeedSchemaError(
            f"field {field!r} is not an ISO-8601 UTC time: {value!r}"
        ) from exc
    return dt.isoformat()


# ── contract validation ───────────────────────────────────────────────────────

def validate_partner_feed_event(
    payload: dict[str, Any],
    *,
    tenant_id: str,
    partner: Optional[str] = None,
    schema_version: Optional[str] = None,
) -> dict[str, Any]:
    """Validate and normalize one partner-feed event.

    Order (all fail closed):
      1. blocked instrument/identity fields → precise REJECTION;
      2. strict allowlist → any unexpected field REJECTED;
      3. schema version supported;
      4. basis is spend-side only (never topup/funding);
      5. money fields are atomic Decimal strings (floats rejected);
      6. event_time/observed_time normalized to UTC; ``occurred_at`` set from
         ``event_time`` when absent;
      7. deterministic idempotency key attached.

    Returns a normalized payload dict ready for
    :meth:`CardLinkedIngestionService.ingest_provider_webhook`. Raises
    :class:`PartnerFeedSchemaError` on any violation.
    """
    if not isinstance(payload, dict):
        raise PartnerFeedSchemaError("partner-feed payload must be a JSON object")

    # 1. hard-blocked instrument/identity fields (precise message: PAN/CVV/etc).
    reject_blocked_fields(payload)

    # 2. STRICT allowlist — reject any field we did not explicitly permit.
    unexpected = sorted(k for k in payload if k not in ALLOWED_PARTNER_FEED_FIELDS)
    if unexpected:
        raise PartnerFeedSchemaError(
            "unexpected field(s) not in the card-linked partner-feed allowlist: "
            + ", ".join(unexpected)
        )

    # 3. schema version.
    version = payload.get("schema_version") or schema_version or CARD_LINKED_PARTNER_FEED_SCHEMA_VERSION
    if version not in SUPPORTED_PARTNER_FEED_SCHEMA_VERSIONS:
        raise PartnerFeedSchemaError(
            f"unsupported partner-feed schema_version {version!r} "
            f"(supported: {sorted(SUPPORTED_PARTNER_FEED_SCHEMA_VERSIONS)})"
        )

    clean: dict[str, Any] = dict(payload)
    clean["schema_version"] = version

    # 4. basis — spend-side only.
    basis = clean.get("basis")
    if basis is not None and str(basis) not in ALLOWED_PARTNER_FEED_BASES:
        raise PartnerFeedSchemaError(
            f"partner-feed basis {basis!r} is not a spend-side basis "
            f"(allowed: {sorted(ALLOWED_PARTNER_FEED_BASES)}; top-up/funding never accepted)"
        )

    # 5. money → atomic Decimal strings.
    for field in _MONEY_FIELDS:
        if field in clean:
            clean[field] = _coerce_money(field, clean[field])

    # 6. time normalization (UTC).
    event_time = clean.get("event_time") or clean.get("occurred_at")
    if event_time:
        clean["occurred_at"] = _to_utc_iso("event_time", event_time)
        clean["event_time"] = clean["occurred_at"]
    if clean.get("observed_time"):
        clean["observed_time"] = _to_utc_iso("observed_time", clean["observed_time"])

    # 7. deterministic idempotency key.
    resolved_partner = str(partner or clean.get("partner") or clean.get("provider") or "partner")
    provider_event_id = str(
        clean.get("provider_event_id") or clean.get("event_id") or clean.get("id") or "event"
    )
    clean["partner"] = resolved_partner
    clean["provider"] = clean.get("provider") or resolved_partner
    clean["provider_event_id"] = clean.get("provider_event_id") or provider_event_id
    # Deterministic flow id from partner + event so redeliveries are stable and
    # the downstream normalizer (which requires an ``id``) always has one.
    clean["id"] = clean.get("id") or f"clf_partner_{resolved_partner}_{provider_event_id}"
    clean["idempotency_key"] = partner_feed_idempotency_key(
        tenant_id, resolved_partner, provider_event_id,
    )
    clean.setdefault("observed_time", _now_iso())
    return clean


# ── HMAC verification ─────────────────────────────────────────────────────────

class CardLinkedPartnerFeedVerifier:
    """HMAC-SHA256 verifier for the card-linked partner feed.

    Reuses the payment-rails HMAC scheme (constant-time compare, prefix
    stripping, ``body_hex`` / ``timestamped_hex`` schemes). The per-tenant
    partner secret is resolved through the BYOK vault; it is never logged,
    persisted, or returned.
    """

    def __init__(
        self,
        vault: Any = None,
        *,
        vault_provider_name: str = PARTNER_FEED_VAULT_PROVIDER,
        signature_scheme: str = "body_hex",
    ) -> None:
        self._vault = vault
        self._vault_provider_name = vault_provider_name
        # "body_hex" signs the raw body; "timestamped_hex" signs f"{ts}.{body}".
        self._signature_scheme = signature_scheme

    def _get_vault(self) -> Any:
        if self._vault is None:
            from services.integrations.providers.payment_rails.base import (
                get_payment_rails_vault,
            )
            self._vault = get_payment_rails_vault()
        return self._vault

    def _provider_name(self, partner: Optional[str]) -> str:
        return f"{self._vault_provider_name}:{partner}" if partner else self._vault_provider_name

    async def resolve_secret(self, tenant_id: str, partner: Optional[str] = None) -> Optional[str]:
        try:
            return await self._get_vault().get_key(tenant_id, self._provider_name(partner))
        except ValueError:
            return None

    def _signed_bytes(self, raw_body: bytes, timestamp: Optional[str]) -> Optional[bytes]:
        if self._signature_scheme == "timestamped_hex":
            if not timestamp:
                return None
            return f"{timestamp}.".encode("utf-8") + raw_body
        return raw_body

    def sign(self, secret: str, raw_body: bytes, timestamp: Optional[str] = None) -> str:
        """Produce a signature the way a partner would (test/dev helper)."""
        signed = self._signed_bytes(raw_body, timestamp)
        if signed is None:
            raise PartnerFeedSignatureError("timestamped_hex scheme requires a timestamp")
        return hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()

    async def verify(
        self,
        tenant_id: str,
        raw_body: bytes,
        signature: Optional[str],
        timestamp: Optional[str] = None,
        partner: Optional[str] = None,
    ) -> bool:
        """Constant-time HMAC verification. False on any missing input/mismatch."""
        if not signature:
            return False
        secret = await self.resolve_secret(tenant_id, partner)
        if not secret:
            return False
        signed = self._signed_bytes(raw_body, timestamp)
        if signed is None:
            return False
        expected = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
        provided = signature.strip()
        for prefix in ("v1=", "s=", "sha256="):
            provided = provided.removeprefix(prefix)
        return hmac.compare_digest(expected, provided)


_default_verifier: Optional[CardLinkedPartnerFeedVerifier] = None


def get_partner_feed_verifier() -> CardLinkedPartnerFeedVerifier:
    global _default_verifier
    if _default_verifier is None:
        _default_verifier = CardLinkedPartnerFeedVerifier()
    return _default_verifier


def reset_partner_feed_verifier() -> None:
    """Test helper — drop the cached default verifier."""
    global _default_verifier
    _default_verifier = None


async def verify_partner_feed_signature(
    tenant_id: str,
    raw_body: bytes,
    signature: Optional[str],
    timestamp: Optional[str] = None,
    partner: Optional[str] = None,
    *,
    verifier: Optional[CardLinkedPartnerFeedVerifier] = None,
) -> None:
    """Fail-closed signature gate.

    Outside local mode an unsigned or invalid-signature payload is REJECTED. In
    local mode an absent signature is tolerated, but a supplied signature is
    still verified so the real verification path is exercised.
    """
    active = verifier or get_partner_feed_verifier()
    if _is_local_env() and signature is None:
        return
    if not await active.verify(tenant_id, raw_body, signature, timestamp, partner):
        raise PartnerFeedSignatureError(
            "unsigned or invalid card-linked partner-feed signature "
            "(fail closed — configure the per-tenant partner secret in the BYOK vault)"
        )
