"""Typed persistence for the integration-consent control plane.

PR-0 created these JSONB-backed stores. This module is the single runtime
repository boundary for them; callers must not create parallel tables or
persist raw connector payloads in these records.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from repositories.repos import BaseRepository


ProcessingProfileStatus = Literal["draft", "active", "suspended", "revoked"]
ManifestStatus = Literal["draft", "approved", "suspended", "revoked"]
DetectionStatus = Literal["manifest_required", "manifested", "ignored"]
ConsentReceiptState = Literal["granted", "denied", "revoked", "expired"]


class CanonicalConsentReceiptInput(BaseModel):
    """API/runtime twin of the generated CanonicalConsentReceipt contract."""

    receipt_id: str
    tenant_id: str
    subject_id: Optional[str] = None
    anonymous_id: Optional[str] = None
    purposes: list[str] = Field(min_length=1)
    state: ConsentReceiptState
    source: str
    provider: Optional[str] = None
    policy_version: str
    jurisdiction_context: Optional[str] = None
    mode: Optional[str] = None
    lawful_basis: Optional[str] = None
    granted_at: Optional[str] = None
    denied_at: Optional[str] = None
    revoked_at: Optional[str] = None
    expires_at: Optional[str] = None
    gpc_observed: Optional[bool] = None
    dnt_observed: Optional[bool] = None
    provider_consent_id: Optional[str] = None
    integrity_hash: str
    idempotency_key: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class TenantProcessingProfile(BaseModel):
    tenant_id: str
    profile_version: str = "1"
    status: ProcessingProfileStatus = "draft"
    policy_version: str
    tenant_admin_approved: bool = False
    approved_purposes: list[str] = Field(default_factory=list)
    allowed_processing_bases: list[str] = Field(default_factory=list)
    prohibited_data_classes: list[str] = Field(default_factory=list)
    fingerprinting_allowed: bool = False
    commercial_stage: str = ""
    risk_tier: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class IntegrationPolicyManifest(BaseModel):
    tenant_id: str
    connector_type: str
    manifest_version: str = "1"
    status: ManifestStatus = "draft"
    policy_version: str
    tenant_admin_approved: bool = False
    provider_admin_installed: bool = False
    approved_purposes: list[str] = Field(default_factory=list)
    processing_basis: Optional[str] = None
    allowed_fields: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DetectedIntegration(BaseModel):
    tenant_id: str
    connector_type: str
    provider: str
    capability: str
    status: DetectionStatus = "manifest_required"
    policy_manifest_version: str
    source: str = "connector_config"
    source_ref: Optional[str] = None
    detected_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class TenantProcessingProfileRepository(BaseRepository):
    """Canonical tenant policy store introduced by the PR-0 seed."""

    def __init__(self) -> None:
        super().__init__("tenant_processing_profiles")

    async def for_tenant(self, tenant_id: str) -> Optional[dict[str, Any]]:
        record = await self.find_by_id(tenant_id)
        if record is not None:
            return record
        rows = await self.find_many(filters={"tenant_id": tenant_id}, limit=1)
        return rows[0] if rows else None

    async def upsert_profile(
        self,
        profile: TenantProcessingProfile,
    ) -> dict[str, Any]:
        return await self.insert(profile.tenant_id, profile.model_dump())


class IntegrationPolicyManifestRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("integration_policy_manifests")

    @staticmethod
    def record_id(tenant_id: str, connector_type: str) -> str:
        return f"{tenant_id}:{connector_type}"

    async def for_connector(
        self,
        tenant_id: str,
        connector_type: str,
    ) -> Optional[dict[str, Any]]:
        record = await self.find_by_id(self.record_id(tenant_id, connector_type))
        if record is not None:
            return record
        rows = await self.find_many(
            filters={"tenant_id": tenant_id, "connector_type": connector_type},
            limit=1,
        )
        return rows[0] if rows else None

    async def upsert_manifest(
        self,
        manifest: IntegrationPolicyManifest,
    ) -> dict[str, Any]:
        return await self.insert(
            self.record_id(manifest.tenant_id, manifest.connector_type),
            manifest.model_dump(),
        )

    async def list_for_tenant(
        self,
        tenant_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return await self.find_many(filters={"tenant_id": tenant_id}, limit=limit)


class DetectedIntegrationRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("detected_integrations")

    @staticmethod
    def record_id(
        tenant_id: str,
        connector_type: str,
        capability: str,
    ) -> str:
        return f"{tenant_id}:{connector_type}:{capability}"

    async def upsert_detection(
        self,
        detection: DetectedIntegration,
    ) -> dict[str, Any]:
        return await self.insert(
            self.record_id(
                detection.tenant_id,
                detection.connector_type,
                detection.capability,
            ),
            detection.model_dump(),
        )

    async def list_for_tenant(
        self,
        tenant_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return await self.find_many(filters={"tenant_id": tenant_id}, limit=limit)


class ConnectorPolicyDecisionRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("connector_policy_decisions")

    async def record(self, decision: dict[str, Any]) -> dict[str, Any]:
        decision_id = str(decision["decisionId"])
        payload = {
            **decision,
            "decision_id": decision_id,
            "tenant_id": decision.get("tenantId"),
            "connector_type": decision.get("connectorType"),
            "policy_version": decision.get("policyVersion"),
        }
        return await self.insert(decision_id, payload)

    async def list_for_tenant(
        self,
        tenant_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return await self.find_many(filters={"tenant_id": tenant_id}, limit=limit)


class ConsentReceiptHistoryRepository(BaseRepository):
    """Append-only receipt evidence; deterministic IDs make retries idempotent."""

    def __init__(self) -> None:
        super().__init__("consent_receipt_history")

    async def append(
        self,
        history_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        existing = await self.find_by_id(history_id)
        if existing is not None:
            return existing
        return await self.insert(history_id, payload)


tenant_processing_profiles = TenantProcessingProfileRepository()
integration_policy_manifests = IntegrationPolicyManifestRepository()
detected_integrations = DetectedIntegrationRepository()
connector_policy_decisions = ConnectorPolicyDecisionRepository()
consent_receipt_history = ConsentReceiptHistoryRepository()
