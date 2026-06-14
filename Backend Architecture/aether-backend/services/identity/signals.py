"""Identity signal extraction from canonical events.

Extracts every IdentitySignal from a normalized backend event payload.
Raw PII values are returned here for hashing by the caller — they are
never stored by this module.
"""

from __future__ import annotations

from typing import Any, Optional

from shared.common.common import utc_now

from .models import IdentitySignal, IdentitySignalType
from .normalization import (
    extract_chain_namespace,
    normalize_anonymous_id,
    normalize_campaign,
    normalize_email,
    normalize_external_id,
    normalize_fingerprint,
    normalize_org_id,
    normalize_phone,
    normalize_session_id,
    normalize_user_id,
    normalize_wallet_address,
)


def extract_signals(
    event: dict[str, Any],
    tenant_id: str,
) -> list[IdentitySignal]:
    """
    Extract identity signals from a normalized backend event payload.

    The ``event`` dict is the normalized payload produced by the ingestion
    pipeline (``_build_normalized_payload`` in batch.py), enriched with
    any properties / context fields the SDK attached.

    Each returned signal carries the raw (or display) value for the caller
    to hash before persistence.  Raw PII signals are never persisted.
    """
    now = utc_now().isoformat()
    event_id = event.get("event_id", "")
    source_platform = _platform(event)
    source_sdk = _sdk(event)
    consent_snapshot = _consent_snapshot(event)

    signals: list[IdentitySignal] = []

    def _sig(
        stype: IdentitySignalType,
        value: str,
        confidence_hint: float = 1.0,
        normalized: str = "",
    ) -> IdentitySignal:
        return IdentitySignal(
            type=stype,
            value=value,
            normalized_value_hash=normalized or None,
            confidence_hint=confidence_hint,
            source="sdk_event",
            observed_at=event.get("timestamp", now),
            source_event_id=event_id,
            source_platform=source_platform,
            source_sdk=source_sdk,
            consent_snapshot=consent_snapshot,
        )

    # ── Core identity fields ──────────────────────────────────────────────

    user_id = event.get("user_id") or ""
    if user_id:
        signals.append(_sig(
            IdentitySignalType.USER_ID,
            user_id,
            confidence_hint=1.0,
            normalized=normalize_user_id(user_id, tenant_id),
        ))

    anon_id = event.get("anonymous_id") or ""
    if anon_id:
        signals.append(_sig(
            IdentitySignalType.ANONYMOUS_ID,
            anon_id,
            confidence_hint=0.7,
            normalized=normalize_anonymous_id(anon_id, tenant_id),
        ))

    session_id = event.get("session_id") or ""
    if session_id:
        signals.append(_sig(
            IdentitySignalType.SESSION_ID,
            session_id,
            confidence_hint=0.5,
            normalized=normalize_session_id(session_id, tenant_id),
        ))

    # ── Context-level signals ─────────────────────────────────────────────

    ctx: dict[str, Any] = event.get("context", {}) or {}

    # Fingerprint (support-only, never hard-links alone)
    fp_ctx = ctx.get("fingerprint") or {}
    fp_id = fp_ctx.get("id") if isinstance(fp_ctx, dict) else fp_ctx
    if fp_id and isinstance(fp_id, str):
        normalized_fp = normalize_fingerprint(fp_id)
        signals.append(_sig(
            IdentitySignalType.DEVICE_FINGERPRINT,
            normalized_fp,
            confidence_hint=0.3,
        ))

    # Org / tenant binding
    org_id = ctx.get("orgId") or ctx.get("org_id") or ""
    if org_id:
        signals.append(_sig(
            IdentitySignalType.ORG_ID,
            org_id,
            confidence_hint=0.9,
            normalized=normalize_org_id(org_id, tenant_id),
        ))

    # Actor / agent context
    actor_id = ctx.get("actorId") or ctx.get("actor_id") or ""
    actor_kind = ctx.get("actorKind") or ctx.get("actor_kind") or ""
    if actor_id and actor_kind == "agent":
        signals.append(_sig(
            IdentitySignalType.AGENT_ID,
            actor_id,
            confidence_hint=0.9,
        ))

    # Delegation / journey
    delegation_id = ctx.get("delegationId") or ""
    if delegation_id:
        signals.append(_sig(
            IdentitySignalType.EXTERNAL_ID,
            delegation_id,
            confidence_hint=0.6,
        ))

    journey_ctx = ctx.get("journey") or {}
    if isinstance(journey_ctx, dict):
        journey_id = journey_ctx.get("journeyId") or ""
        if journey_id:
            signals.append(_sig(
                IdentitySignalType.JOURNEY_ID,
                journey_id,
                confidence_hint=0.5,
            ))

    # Campaign attribution
    campaign_ctx = ctx.get("campaign") or {}
    if isinstance(campaign_ctx, dict):
        normalized_campaign = normalize_campaign(campaign_ctx)
        campaign_id = (
            normalized_campaign.get("campaign")
            or normalized_campaign.get("source")
        )
        if campaign_id:
            signals.append(_sig(
                IdentitySignalType.CAMPAIGN_ID,
                campaign_id,
                confidence_hint=0.2,
            ))

    # ── Properties-level signals ──────────────────────────────────────────

    props: dict[str, Any] = event.get("properties") or {}

    # Email (raw — caller must hash)
    email_raw = props.get("email") or ""
    if email_raw:
        normalized_email = normalize_email(email_raw)
        if normalized_email:
            signals.append(_sig(
                IdentitySignalType.EMAIL_HASH,
                normalized_email,   # caller hashes this
                confidence_hint=0.9,
            ))

    # Phone (raw — caller must hash)
    phone_raw = props.get("phone") or ""
    if phone_raw:
        normalized_phone = normalize_phone(phone_raw)
        if normalized_phone:
            signals.append(_sig(
                IdentitySignalType.PHONE_HASH,
                normalized_phone,   # caller hashes this
                confidence_hint=0.9,
            ))

    # External / customer ID
    ext_id = (
        props.get("external_id")
        or props.get("externalId")
        or props.get("customer_id")
        or props.get("customerId")
        or ""
    )
    if ext_id:
        signals.append(_sig(
            IdentitySignalType.EXTERNAL_ID,
            normalize_external_id(str(ext_id), tenant_id),
            confidence_hint=1.0,
        ))

    # Commerce / payment customer IDs
    commerce_cid = props.get("commerce_customer_id") or props.get("commerceCustomerId") or ""
    if commerce_cid:
        signals.append(_sig(
            IdentitySignalType.COMMERCE_CUSTOMER_ID,
            str(commerce_cid),
            confidence_hint=0.95,
        ))

    payment_cid = props.get("payment_customer_id") or props.get("paymentCustomerId") or ""
    if payment_cid:
        signals.append(_sig(
            IdentitySignalType.PAYMENT_CUSTOMER_ID,
            str(payment_cid),
            confidence_hint=0.95,
        ))

    account_id = props.get("account_id") or props.get("accountId") or ""
    if account_id:
        signals.append(_sig(
            IdentitySignalType.ACCOUNT_ID,
            str(account_id),
            confidence_hint=0.9,
        ))

    # Installation / browser IDs
    install_id = props.get("installation_id") or props.get("installationId") or ""
    if install_id:
        signals.append(_sig(
            IdentitySignalType.INSTALLATION_ID,
            str(install_id),
            confidence_hint=0.7,
        ))

    browser_id = props.get("browser_id") or props.get("browserId") or ""
    if browser_id:
        signals.append(_sig(
            IdentitySignalType.BROWSER_ID,
            str(browser_id),
            confidence_hint=0.6,
        ))

    mobile_install_id = props.get("mobile_install_id") or props.get("mobileInstallId") or ""
    if mobile_install_id:
        signals.append(_sig(
            IdentitySignalType.MOBILE_INSTALL_ID,
            str(mobile_install_id),
            confidence_hint=0.7,
        ))

    # ── Wallet signals ────────────────────────────────────────────────────

    # Single wallet (backwards-compatible)
    wallet_address = (
        props.get("wallet_address")
        or props.get("walletAddress")
        or props.get("address")
        or ""
    )
    if wallet_address:
        chain_ns = extract_chain_namespace(props)
        normalized_addr = normalize_wallet_address(wallet_address, chain_ns)
        is_verified = bool(
            props.get("wallet_signature_verified")
            or props.get("walletSignatureVerified")
        )
        sig_type = (
            IdentitySignalType.WALLET_SIGNATURE_VERIFIED
            if is_verified
            else IdentitySignalType.WALLET_ADDRESS
        )
        confidence_hint = 0.95 if is_verified else 0.6
        signals.append(_sig(sig_type, normalized_addr, confidence_hint=confidence_hint))

    # Multi-wallet array
    wallets: list[Any] = props.get("wallets") or []
    for w in wallets:
        if not isinstance(w, dict):
            continue
        addr = w.get("address") or ""
        if not addr:
            continue
        chain_ns = extract_chain_namespace(w)
        normalized_addr = normalize_wallet_address(addr, chain_ns)
        is_verified = bool(w.get("verified") or w.get("signature_verified"))
        sig_type = (
            IdentitySignalType.WALLET_SIGNATURE_VERIFIED
            if is_verified
            else IdentitySignalType.WALLET_ADDRESS
        )
        confidence_hint = 0.95 if is_verified else 0.6
        signals.append(_sig(sig_type, normalized_addr, confidence_hint=confidence_hint))

    # Deduplicate: drop signals whose (type, value) pair appears twice
    seen: set[tuple] = set()
    deduped: list[IdentitySignal] = []
    for s in signals:
        key = (s.type, s.value)
        if key not in seen:
            seen.add(key)
            deduped.append(s)

    return deduped


# ── Private helpers ───────────────────────────────────────────────────────────

def _platform(event: dict) -> str:
    ctx = event.get("context") or {}
    lib = ctx.get("library") or {}
    return lib.get("name") or event.get("source") or "sdk"


def _sdk(event: dict) -> str:
    ctx = event.get("context") or {}
    lib = ctx.get("library") or {}
    return lib.get("version") or ""


def _consent_snapshot(event: dict) -> Optional[dict]:
    ctx = event.get("context") or {}
    consent = ctx.get("consent")
    if isinstance(consent, dict):
        return consent
    return None
