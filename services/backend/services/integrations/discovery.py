"""Flag-gated integration discovery and policy-manifest lifecycle.

Discovery observes tenant-scoped connector configuration metadata only. It
never reads connector secrets, enables a connector, approves a manifest, or
creates consent evidence. Approval remains an explicit tenant-admin action and
the runtime processing authority continues to require subject consent where the
canonical registry says it is required.
"""
from __future__ import annotations

from typing import Any, Iterable

from config.settings import settings
from shared.common.common import BadRequestError, ForbiddenError
from shared.privacy.generated_integration_consent import (
    INTEGRATION_CONSENT_REGISTRY_VERSION,
)

from services.consent.control_plane import (
    DetectedIntegration,
    IntegrationPolicyManifest,
    detected_integrations,
    integration_policy_manifests,
)
from services.consent.integration_governance import (
    get_integration_consent_policy,
    normalize_connector_type,
)
from services.integrations.connectors.registry import descriptor_for


DISCOVERY_DISABLED = "Integration discovery is not enabled for this deployment"
MANIFEST_APPROVAL_INCOMPLETE = "Integration manifest approval is incomplete"


def integration_discovery_enabled() -> bool:
    rollout = settings.integration_consent
    return bool(
        rollout.control_plane_v2_enabled
        and rollout.integration_discovery_enabled
    )


def require_integration_discovery() -> None:
    if not integration_discovery_enabled():
        raise ForbiddenError(DISCOVERY_DISABLED)


def _capabilities(policy: dict[str, Any]) -> list[str]:
    return list(policy.get("supportedCapabilities") or ["configured"])


async def discover_configured_integrations(
    tenant_id: str,
    configured_connectors: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Persist registry-backed detections from non-secret connector metadata."""

    require_integration_discovery()
    discovered: list[dict[str, Any]] = []
    for configured in configured_connectors:
        connector_type = normalize_connector_type(
            str(configured.get("connector_type") or "")
        )
        policy = get_integration_consent_policy(connector_type)
        descriptor = descriptor_for(connector_type)
        if not connector_type or policy is None or descriptor is None:
            continue
        existing_manifest = await integration_policy_manifests.for_connector(
            tenant_id,
            connector_type,
        )
        status = "manifested" if existing_manifest is not None else "manifest_required"
        for capability in _capabilities(policy):
            detection = DetectedIntegration(
                tenant_id=tenant_id,
                connector_type=connector_type,
                provider=str(policy["provider"]),
                capability=capability,
                status=status,
                policy_manifest_version=INTEGRATION_CONSENT_REGISTRY_VERSION,
                source_ref=(
                    str(configured["config_id"])
                    if configured.get("config_id")
                    else None
                ),
                metadata={
                    "enabled": bool(configured.get("enabled")),
                    "secret_configured": bool(
                        configured.get("secret_configured")
                    ),
                },
            )
            discovered.append(
                await detected_integrations.upsert_detection(detection)
            )
    return discovered


async def create_draft_manifest(
    tenant_id: str,
    connector_type: str,
    *,
    actor_id: str,
) -> dict[str, Any]:
    """Create a non-authoritative draft using registry-declared requirements."""

    require_integration_discovery()
    canonical_type = normalize_connector_type(connector_type)
    policy = get_integration_consent_policy(canonical_type)
    if policy is None:
        raise BadRequestError(f"unknown integration policy: {canonical_type}")
    default_basis = str(policy["defaultProcessingBasis"])
    supported_bases = set(policy["supportedProcessingBases"])
    manifest = IntegrationPolicyManifest(
        tenant_id=tenant_id,
        connector_type=canonical_type,
        status="draft",
        policy_version=INTEGRATION_CONSENT_REGISTRY_VERSION,
        tenant_admin_approved=False,
        provider_admin_installed=False,
        approved_purposes=[],
        processing_basis=(
            default_basis if default_basis in supported_bases else None
        ),
        allowed_fields=[],
        metadata={
            "created_by": actor_id,
            "registry_required_purposes": list(
                policy["requiredSubjectPurposes"]
            ),
            "registry_data_categories": list(policy["dataCategories"]),
        },
    )
    stored = await integration_policy_manifests.upsert_manifest(manifest)
    await _mark_detections_manifested(tenant_id, canonical_type)
    return stored


async def approve_manifest(
    tenant_id: str,
    connector_type: str,
    *,
    approved_purposes: Iterable[str],
    processing_basis: str,
    allowed_fields: Iterable[str],
    provider_admin_installed: bool,
    actor_id: str,
) -> dict[str, Any]:
    """Validate and persist explicit tenant-admin manifest approval."""

    require_integration_discovery()
    canonical_type = normalize_connector_type(connector_type)
    policy = get_integration_consent_policy(canonical_type)
    if policy is None:
        raise BadRequestError(f"unknown integration policy: {canonical_type}")

    purposes = sorted(set(approved_purposes))
    fields = sorted({field.strip() for field in allowed_fields if field.strip()})
    required_purposes = set(policy["requiredSubjectPurposes"])
    supported_bases = set(policy["supportedProcessingBases"])
    provider_install_ok = (
        not policy["requiresProviderAdminInstall"] or provider_admin_installed
    )
    if (
        not required_purposes.issubset(purposes)
        or processing_basis not in supported_bases
        or not fields
        or not provider_install_ok
    ):
        raise BadRequestError(MANIFEST_APPROVAL_INCOMPLETE)

    manifest = IntegrationPolicyManifest(
        tenant_id=tenant_id,
        connector_type=canonical_type,
        status="approved",
        policy_version=INTEGRATION_CONSENT_REGISTRY_VERSION,
        tenant_admin_approved=True,
        provider_admin_installed=provider_admin_installed,
        approved_purposes=purposes,
        processing_basis=processing_basis,
        allowed_fields=fields,
        metadata={
            "approved_by": actor_id,
            "registry_version": INTEGRATION_CONSENT_REGISTRY_VERSION,
        },
    )
    stored = await integration_policy_manifests.upsert_manifest(manifest)
    await _mark_detections_manifested(tenant_id, canonical_type)
    return stored


async def list_detections(tenant_id: str) -> list[dict[str, Any]]:
    require_integration_discovery()
    return await detected_integrations.list_for_tenant(tenant_id, limit=1000)


async def list_manifests(tenant_id: str) -> list[dict[str, Any]]:
    require_integration_discovery()
    return await integration_policy_manifests.list_for_tenant(
        tenant_id,
        limit=1000,
    )


async def _mark_detections_manifested(
    tenant_id: str,
    connector_type: str,
) -> None:
    detections = await detected_integrations.list_for_tenant(
        tenant_id,
        limit=1000,
    )
    for record in detections:
        if record.get("connector_type") != connector_type:
            continue
        detection = DetectedIntegration.model_validate(
            {**record, "status": "manifested"}
        )
        await detected_integrations.upsert_detection(detection)
