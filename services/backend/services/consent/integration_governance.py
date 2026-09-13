"""Registry-backed integration processing authority.

This is the canonical runtime that turns the generated integration-consent
policy plus tenant manifests and server consent receipts into one explainable,
persisted ``ProcessingDecision``. Unknown or incomplete policy always fails
closed and requires quarantine.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Iterable, Optional
from uuid import uuid4

from services.consent.authority import (
    evaluate_consent,
    get_latest_consent_receipt,
)
from services.consent.control_plane import (
    connector_policy_decisions,
    integration_policy_manifests,
    tenant_processing_profiles,
)
from shared.privacy.generated_integration_consent import (
    INTEGRATION_CONSENT_POLICY_BY_TYPE,
    INTEGRATION_CONSENT_REGISTRY_VERSION,
    ProcessingDecision,
)


CONNECTOR_TYPE_ALIASES = {
    "webhook": "generic_webhook",
}

UNKNOWN_CONNECTOR_POLICY = "unknown_connector_policy"
TENANT_PROCESSING_PROFILE_MISSING = "tenant_processing_profile_missing"
TENANT_PROCESSING_PROFILE_INACTIVE = "tenant_processing_profile_inactive"
INTEGRATION_MANIFEST_MISSING = "integration_policy_manifest_missing"
INTEGRATION_MANIFEST_INACTIVE = "integration_policy_manifest_inactive"
TENANT_ADMIN_APPROVAL_REQUIRED = "tenant_admin_approval_required"
PROVIDER_ADMIN_INSTALL_REQUIRED = "provider_admin_install_required"
PROCESSING_BASIS_REQUIRED = "processing_basis_required"
PROCESSING_BASIS_UNSUPPORTED = "processing_basis_unsupported"
PURPOSE_REQUIRED = "purpose_required"
PURPOSE_NOT_DECLARED = "purpose_not_declared"
PURPOSE_NOT_APPROVED = "purpose_not_approved"
DATA_CLASSIFICATION_DENIED = "data_classification_denied"
PAYLOAD_FIELD_MANIFEST_REQUIRED = "payload_field_manifest_required"
UNKNOWN_PAYLOAD_FIELDS = "unknown_payload_fields"
CONSENT_RECEIPT_MISSING = "consent_receipt_missing"


def normalize_connector_type(connector_type: str) -> str:
    normalized = (connector_type or "").strip().lower()
    return CONNECTOR_TYPE_ALIASES.get(normalized, normalized)


def get_integration_consent_policy(connector_type: str) -> Optional[dict]:
    return INTEGRATION_CONSENT_POLICY_BY_TYPE.get(
        normalize_connector_type(connector_type)
    )


def integration_governance_descriptor(connector_type: str) -> dict:
    """Return snake_case descriptor fields derived only from the registry."""

    policy = get_integration_consent_policy(connector_type)
    if policy is None:
        return {
            "governance_connector_type": normalize_connector_type(connector_type),
            "governance_policy_version": INTEGRATION_CONSENT_REGISTRY_VERSION,
            "governance_policy_known": False,
        }
    return {
        "governance_connector_type": policy["connectorType"],
        "governance_policy_version": INTEGRATION_CONSENT_REGISTRY_VERSION,
        "governance_policy_known": True,
        "required_subject_purposes": list(policy["requiredSubjectPurposes"]),
        "supported_processing_bases": list(policy["supportedProcessingBases"]),
        "default_processing_basis": policy["defaultProcessingBasis"],
        "data_categories": list(policy["dataCategories"]),
        "identity_signals": list(policy["identitySignals"]),
        "allows_identity_linking": bool(policy["allowsIdentityLinking"]),
        "allows_graph_projection": bool(policy["allowsGraphProjection"]),
        "allows_model_training": bool(policy["allowsModelTraining"]),
        "allows_pre_consent_processing": bool(
            policy["allowsPreConsentProcessing"]
        ),
        "retention_class": policy["retentionClass"],
        "raw_payload_policy": policy["rawPayloadPolicy"],
        "quarantine_policy": policy["quarantinePolicy"],
        "provider_consent_bridge": policy["providerConsentBridge"],
        "provider_signature_scheme": policy["providerSignatureScheme"],
        "supports_outbound_activation": bool(
            policy["supportsOutboundActivation"]
        ),
        "requires_tenant_admin_approval": bool(
            policy["requiresTenantAdminApproval"]
        ),
        "requires_admin_install": bool(policy["requiresProviderAdminInstall"]),
        "supports_historical_backfill": bool(
            policy["supportsHistoricalBackfill"]
        ),
    }


def _decision(
    *,
    tenant_id: str,
    connector_type: str,
    source_kind: str,
    subject_id: Optional[str],
    anonymous_id: Optional[str],
    purpose: Optional[str],
    processing_basis: Optional[str],
    policy: Optional[dict],
    allowed: bool,
    reason_code: Optional[str],
    consent_receipt_id: Optional[str] = None,
) -> ProcessingDecision:
    return ProcessingDecision(
        decisionId=f"icpd_{uuid4().hex}",
        tenantId=tenant_id,
        connectorType=normalize_connector_type(connector_type),
        sourceKind=source_kind,
        subjectId=subject_id,
        anonymousId=anonymous_id,
        purpose=purpose,
        processingBasis=processing_basis,
        allowed=allowed,
        reasonCode=reason_code,
        identityLinkingAllowed=bool(
            allowed and policy and policy["allowsIdentityLinking"]
        ),
        graphProjectionAllowed=bool(
            allowed and policy and policy["allowsGraphProjection"]
        ),
        modelTrainingAllowed=bool(
            allowed and policy and policy["allowsModelTraining"]
        ),
        activationAllowed=bool(
            allowed and policy and policy["supportsOutboundActivation"]
        ),
        retentionClass=(
            str(policy["retentionClass"]) if policy else "quarantine_only"
        ),
        quarantineRequired=not allowed,
        policyVersion=INTEGRATION_CONSENT_REGISTRY_VERSION,
        consentReceiptId=consent_receipt_id,
        evaluatedAt=datetime.now(timezone.utc).isoformat(),
    )


async def _persist(
    decision: ProcessingDecision,
    *,
    persist: bool,
) -> ProcessingDecision:
    if persist:
        await connector_policy_decisions.record(asdict(decision))
    return decision


async def evaluate_connector_processing(
    tenant_id: str,
    connector_type: str,
    *,
    source_kind: str = "connector",
    payload_fields: Optional[Iterable[str]] = None,
    subject_id: Optional[str] = None,
    anonymous_id: Optional[str] = None,
    purpose: Optional[str] = None,
    processing_basis: Optional[str] = None,
    tenant_admin_approved: Optional[bool] = None,
    provider_admin_installed: Optional[bool] = None,
    action: str = "process",
    persist: bool = True,
) -> ProcessingDecision:
    """Evaluate one connector action and persist the explainable decision.

    Configuration/sync actions prove tenant-level governance readiness. Actual
    subject processing additionally requires an authoritative receipt unless
    the canonical policy explicitly permits pre-consent processing under the
    selected non-consent basis.
    """

    canonical_type = normalize_connector_type(connector_type)
    policy = get_integration_consent_policy(canonical_type)

    async def deny(
        reason: str,
        *,
        effective_purpose: Optional[str] = purpose,
        effective_basis: Optional[str] = processing_basis,
    ) -> ProcessingDecision:
        return await _persist(
            _decision(
                tenant_id=tenant_id,
                connector_type=canonical_type,
                source_kind=source_kind,
                subject_id=subject_id,
                anonymous_id=anonymous_id,
                purpose=effective_purpose,
                processing_basis=effective_basis,
                policy=policy,
                allowed=False,
                reason_code=reason,
            ),
            persist=persist,
        )

    if policy is None:
        return await deny(UNKNOWN_CONNECTOR_POLICY)

    profile = await tenant_processing_profiles.for_tenant(tenant_id)
    if profile is None:
        return await deny(TENANT_PROCESSING_PROFILE_MISSING)
    profile_status = str(
        profile.get("status") or profile.get("policy_state") or ""
    ).lower()
    if profile_status != "active":
        return await deny(TENANT_PROCESSING_PROFILE_INACTIVE)

    manifest = await integration_policy_manifests.for_connector(
        tenant_id,
        canonical_type,
    )
    if manifest is None:
        return await deny(INTEGRATION_MANIFEST_MISSING)
    if str(manifest.get("status") or "").lower() != "approved":
        return await deny(INTEGRATION_MANIFEST_INACTIVE)

    tenant_approved = (
        tenant_admin_approved
        if tenant_admin_approved is not None
        else bool(
            manifest.get("tenant_admin_approved")
            or profile.get("tenant_admin_approved")
        )
    )
    if policy["requiresTenantAdminApproval"] and not tenant_approved:
        return await deny(TENANT_ADMIN_APPROVAL_REQUIRED)

    provider_installed = (
        provider_admin_installed
        if provider_admin_installed is not None
        else bool(manifest.get("provider_admin_installed"))
    )
    if policy["requiresProviderAdminInstall"] and not provider_installed:
        return await deny(PROVIDER_ADMIN_INSTALL_REQUIRED)

    effective_basis = (
        processing_basis
        or manifest.get("processing_basis")
        or policy["defaultProcessingBasis"]
    )
    supported_bases = set(policy["supportedProcessingBases"])
    if not effective_basis or effective_basis not in supported_bases:
        reason = (
            PROCESSING_BASIS_REQUIRED
            if policy["defaultProcessingBasis"] not in supported_bases
            else PROCESSING_BASIS_UNSUPPORTED
        )
        return await deny(reason, effective_basis=effective_basis)
    profile_bases = set(profile.get("allowed_processing_bases") or [])
    if profile_bases and effective_basis not in profile_bases:
        return await deny(
            PROCESSING_BASIS_UNSUPPORTED,
            effective_basis=effective_basis,
        )

    required_purposes = set(policy["requiredSubjectPurposes"])
    approved_purposes = set(manifest.get("approved_purposes") or [])
    if not required_purposes.issubset(approved_purposes):
        return await deny(
            PURPOSE_NOT_APPROVED,
            effective_basis=effective_basis,
        )
    profile_purposes = set(profile.get("approved_purposes") or [])
    if profile_purposes and not required_purposes.issubset(profile_purposes):
        return await deny(
            PURPOSE_NOT_APPROVED,
            effective_basis=effective_basis,
        )

    prohibited = {
        str(item).strip().lower()
        for item in (profile.get("prohibited_data_classes") or [])
    }
    policy_categories = {
        str(item).strip().lower() for item in policy["dataCategories"]
    }
    if prohibited & policy_categories:
        return await deny(
            DATA_CLASSIFICATION_DENIED,
            effective_basis=effective_basis,
        )

    normalized_fields = {
        str(item).strip() for item in (payload_fields or []) if str(item).strip()
    }
    allowed_fields = {
        str(item).strip()
        for item in (manifest.get("allowed_fields") or [])
        if str(item).strip()
    }
    if normalized_fields and not allowed_fields:
        return await deny(
            PAYLOAD_FIELD_MANIFEST_REQUIRED,
            effective_basis=effective_basis,
        )
    if normalized_fields - allowed_fields:
        return await deny(
            UNKNOWN_PAYLOAD_FIELDS,
            effective_basis=effective_basis,
        )

    # Enable/sync establish tenant-level readiness. Per-subject enforcement is
    # performed on the later processing call once a subject/purpose is known.
    effective_purpose = purpose
    if action not in {"enable", "sync", "configure"}:
        if not effective_purpose:
            if len(required_purposes) == 1:
                effective_purpose = next(iter(required_purposes))
            else:
                return await deny(
                    PURPOSE_REQUIRED,
                    effective_basis=effective_basis,
                )
        if effective_purpose not in required_purposes:
            return await deny(
                PURPOSE_NOT_DECLARED,
                effective_purpose=effective_purpose,
                effective_basis=effective_basis,
            )
        if effective_purpose not in approved_purposes:
            return await deny(
                PURPOSE_NOT_APPROVED,
                effective_purpose=effective_purpose,
                effective_basis=effective_basis,
            )

        requires_receipt = (
            effective_basis == "consent"
            or not bool(policy["allowsPreConsentProcessing"])
        )
        receipt = None
        if requires_receipt:
            if not subject_id and not anonymous_id:
                return await deny(
                    CONSENT_RECEIPT_MISSING,
                    effective_purpose=effective_purpose,
                    effective_basis=effective_basis,
                )
            consent_allowed, consent_reason = await evaluate_consent(
                tenant_id,
                subject_id,
                anonymous_id,
                effective_purpose,
            )
            # Compose the established purpose-policy engine so connector
            # decisions join existing consent audit evidence.
            from services.policy.engine import consent_policy_engine

            policy_decision = await consent_policy_engine.decide(
                tenant_id=tenant_id,
                actor_id="integration-consent-authority",
                action="collect_event",
                resource_type="integration_connector",
                resource_id=canonical_type,
                subject_ref=subject_id or anonymous_id,
                purpose=effective_purpose,
                granted_purposes=(
                    [effective_purpose] if consent_allowed else []
                ),
                consent_policy_version=INTEGRATION_CONSENT_REGISTRY_VERSION,
            )
            if not consent_allowed or not policy_decision.allowed:
                return await deny(
                    consent_reason or policy_decision.denied_reason
                    or CONSENT_RECEIPT_MISSING,
                    effective_purpose=effective_purpose,
                    effective_basis=effective_basis,
                )
            receipt = await get_latest_consent_receipt(
                tenant_id,
                effective_purpose,
                subject_id=subject_id,
                anonymous_id=anonymous_id,
            )

        decision = _decision(
            tenant_id=tenant_id,
            connector_type=canonical_type,
            source_kind=source_kind,
            subject_id=subject_id,
            anonymous_id=anonymous_id,
            purpose=effective_purpose,
            processing_basis=effective_basis,
            policy=policy,
            allowed=True,
            reason_code=None,
            consent_receipt_id=(
                str(receipt.get("receipt_id")) if receipt else None
            ),
        )
        return await _persist(decision, persist=persist)

    decision = _decision(
        tenant_id=tenant_id,
        connector_type=canonical_type,
        source_kind=source_kind,
        subject_id=subject_id,
        anonymous_id=anonymous_id,
        purpose=effective_purpose,
        processing_basis=effective_basis,
        policy=policy,
        allowed=True,
        reason_code=None,
    )
    return await _persist(decision, persist=persist)
