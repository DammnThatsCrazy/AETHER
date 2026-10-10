"""Capture customer identity evidence from durable provider records.

This adapter is called by the provider runtime only after raw-record persistence
returns a newly inserted outcome. Provider observations are
source-scoped and hashed; they are deliberately not eligible for canonical
candidate resolution because provider sync/webhook lifecycles do not yet expose
a durable current-commit/rollback boundary.
"""

from __future__ import annotations

from typing import Any, Iterable

from identity.identity.claim_normalizer import normalize_email, normalize_phone, normalize_provider_id
from identity.identity.hashing import hash_value
from identity.identity.repository import IdentityResolutionRepository
from identity.identity.source_identity_registry import SourceIdentityRegistry
from identity.identity.provider_evidence_anchors import ProviderIdentityEvidenceAnchorRepository
from shared.integration_contracts.events import RawProviderRecord


def _customer_evidence(record: RawProviderRecord) -> tuple[str | None, str | None, str | None]:
    payload = record.payload if isinstance(record.payload, dict) else {}
    provider = record.provider_identity.split(".", 1)[0].lower()
    if provider in {"etsy", "tiktok", "walmart"}:
        # Provider-specific parsers deliberately whitelist customer fields.
        # Receipt/order IDs and seller/store account IDs are not person IDs.
        from importlib import import_module

        extractor = import_module(f"connectors.providers.{provider}.identity").extract_customer_identity
        external_id, email, phone = extractor(payload)
    elif provider == "amazon":
        from connectors.providers.amazon.identity_evidence import extract_amazon_customer_evidence

        external_id, email, phone = extract_amazon_customer_evidence(record)
    elif provider == "ebay":
        from connectors.providers.ebay.identity_evidence import extract_ebay_customer_evidence

        external_id, email, phone = extract_ebay_customer_evidence(record)
    elif provider == "shopify":
        customer = payload.get("customer")
        customer = customer if isinstance(customer, dict) else {}
        external_id = customer.get("id") or payload.get("customer_id")
        email = customer.get("email") or payload.get("email")
        phone = customer.get("phone") or payload.get("phone")
    elif provider == "woocommerce":
        billing = payload.get("billing")
        billing = billing if isinstance(billing, dict) else {}
        external_id = payload.get("customer_id")
        email = billing.get("email") or payload.get("email")
        phone = billing.get("phone") or payload.get("phone")
    else:
        return None, None, None
    clean_id = str(external_id).strip() if external_id not in (None, "", 0, "0") else None
    clean_email = str(email).strip() if email else None
    clean_phone = str(phone).strip() if phone else None
    return clean_id, clean_email, clean_phone


async def capture_durable_provider_customer_evidence(
    records: Iterable[RawProviderRecord],
    outcomes: Any,
    *,
    tenant_id: str,
    connection_id: str,
    account_id: str,
    lifecycle_type: str,
    lifecycle_id: str,
) -> int:
    """Persist source identities and hashed claims for durably accepted records.

    ``outcomes`` must be the ``(record, was_new)`` result from
    ``RawProviderRecordStore.ingest``. Newly inserted rows are captured. On a
    dedupe hit, the retry may refresh an anchor only when an existing claim
    proves the exact raw checksum and schema version; otherwise the incoming
    payload may differ from the payload Bronze retained. A missing/malformed
    outcome or missing lifecycle ID fails closed and captures nothing. A
    pending durable anchor is written for each claim; its
    owning sync/inbox lifecycle must mark the anchor completed before SDK
    candidate lookup will expose it.
    """
    if not lifecycle_id:
        return 0
    accepted: dict[tuple[str, str, str], str | None] = {}
    try:
        for item in outcomes or []:
            record, was_new = item
            # Keep duplicate outcomes too. A provider may retry a failed sync
            # after Bronze has already accepted the record. Such a retry may
            # refresh the lifecycle anchor only when the claim registry proves
            # that this exact raw checksum/schema was previously captured.
            # The durable identity claim is the fingerprint witness; changed
            # duplicate payloads never become evidence.
            key = (record.provider_identity, record.provider_record_id, record.schema_version)
            if was_new:
                accepted[key] = record.checksum
            else:
                # Preserve an earlier new outcome for duplicate records in the
                # same batch, and retain None as the dedup-retry marker when
                # this lifecycle only saw already-stored Bronze rows.
                accepted.setdefault(key, None)
    except (TypeError, ValueError):
        return 0
    identity_repo = IdentityResolutionRepository()
    registry = SourceIdentityRegistry(identity_repo)
    anchors = ProviderIdentityEvidenceAnchorRepository()
    captured = 0
    for record in records:
        outcome_key = (record.provider_identity, record.provider_record_id, record.schema_version)
        if outcome_key not in accepted:
            continue
        durable_checksum = accepted[outcome_key]
        if durable_checksum is not None and durable_checksum != record.checksum:
            # A second payload with the same Bronze idempotency key is not the
            # payload that won the durable insert in this batch.
            continue
        external_id, email, phone = _customer_evidence(record)
        if not external_id and not email and not phone:
            continue
        provider = record.provider_identity.split(".", 1)[0].lower()
        namespace_anchor = account_id.strip() or connection_id.strip()
        if not namespace_anchor:
            # No stable provider account scope: do not create a broadly scoped identity.
            continue
        source_record_id = external_id or record.provider_record_id
        source = await registry.register_source_identity(
            tenant_id=tenant_id,
            source_system_id=record.provider_identity,
            source_kind="connector",
            source_namespace=f"{provider}:{namespace_anchor}:{connection_id}",
            external_id=external_id,
            account_id=namespace_anchor,
            source_record_id=record.provider_record_id,
        )
        # A Bronze idempotency hit does not prove that the incoming payload is
        # the immutable payload already stored there. For a retry, require at
        # least one exact existing provider claim fingerprint before allowing
        # any claims from this record to refresh their lifecycle anchor.
        if durable_checksum is None:
            verified_duplicate = False
            for claim_type, value in (
                ("external_customer_id", external_id),
                ("email", email),
                ("phone", phone),
            ):
                if not value:
                    continue
                if claim_type == "email":
                    normalized = normalize_email(value)
                    digest = hash_value(normalized, scope=f"email:{tenant_id}")
                elif claim_type == "phone":
                    normalized = normalize_phone(value)
                    digest = hash_value(normalized, scope=f"phone:{tenant_id}")
                else:
                    normalized = normalize_provider_id(value)
                    digest = normalized
                prior = await identity_repo.find_claim(
                    tenant_id,
                    source.id,
                    claim_type,
                    digest,
                    source_record_id=record.provider_record_id,
                )
                if (
                    prior
                    and prior.get("provider_raw_checksum") == record.checksum
                    and prior.get("provider_raw_schema_version") == record.schema_version
                ):
                    verified_duplicate = True
                    break
            if not verified_duplicate:
                continue
        anchored_claims = 0
        for claim_type, value in (
            ("external_customer_id", external_id),
            ("email", email),
            ("phone", phone),
        ):
            if not value:
                continue
            await registry.upsert_identity_claim(
                tenant_id=tenant_id,
                source_identity_id=source.id,
                claim_type=claim_type,
                raw_value=value,
                verification_status="observed",
                pii_classification="sensitive" if claim_type in {"email", "phone"} else "low",
                source_record_id=record.provider_record_id,
                hash_sensitive_value=True,
            )
            if claim_type == "email":
                normalized = normalize_email(value)
                claim_digest = hash_value(normalized, scope=f"email:{tenant_id}")
            elif claim_type == "phone":
                normalized = normalize_phone(value)
                claim_digest = hash_value(normalized, scope=f"phone:{tenant_id}")
            else:
                # Provider customer IDs are normalized but intentionally not
                # treated as email/phone PII digests by the registry.
                normalized = normalize_provider_id(value)
                claim_digest = normalized
            # SourceIdentityRegistry's new-claim return object predates the
            # repository-generated row ID. Read the persisted row so the anchor
            # binds the exact durable claim key used by candidate lookup.
            persisted_claim = await identity_repo.find_claim(
                tenant_id,
                source.id,
                claim_type,
                claim_digest,
                source_record_id=record.provider_record_id,
            )
            claim_id = persisted_claim.get("id") if persisted_claim else None
            if claim_id:
                provenance_claim = await identity_repo.update_claim_provider_provenance(
                    tenant_id,
                    str(claim_id),
                    raw_checksum=record.checksum,
                    raw_schema_version=record.schema_version,
                )
                if provenance_claim is None:
                    continue
                await anchors.set_pending(
                    tenant_id=tenant_id,
                    claim_id=str(claim_id),
                    source_identity_id=source.id,
                    source_record_id=record.provider_record_id,
                    raw_checksum=record.checksum,
                    raw_schema_version=record.schema_version,
                    provider_identity=record.provider_identity,
                    connection_id=connection_id,
                    account_id=namespace_anchor,
                    lifecycle_type=lifecycle_type,
                    lifecycle_id=lifecycle_id,
                )
                anchored_claims += 1
        if anchored_claims:
            # A source-scoped provisional profile supports imported history and
            # review UX. It does not turn provider claims into merge authority;
            # candidate eligibility still depends on the durable lifecycle
            # anchor and later server-authoritative identity-link consent.
            await registry.ensure_provisional_profile(
                tenant_id=tenant_id,
                source_identity_id=source.id,
            )
            captured += 1
    return captured


__all__ = ["capture_durable_provider_customer_evidence"]
