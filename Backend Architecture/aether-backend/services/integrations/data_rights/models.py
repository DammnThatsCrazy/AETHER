"""
Aether — Data Rights Ledger Models

All data use decisions are fail-closed: absent an explicit grant, use is denied.

DataRightsGrant is the canonical record for every data use permission:
- Tenant BYOD connectors: tenant_lake_allowed=True by default only
- Olympus provider sources: olympus_baseline_allowed=True, model_training=False (requires compliance review)
- Cross-tenant aggregates: cross_tenant_aggregate_allowed=False always by default
- Model training: model_training_allowed=False always by default

BYOK credential does NOT imply lake ingestion rights, Olympus baseline use,
model training, or aggregate use. These require separate DataRightsGrant.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class GrantStatus(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"
    PENDING_REVIEW = "pending_review"
    SUSPENDED = "suspended"


class LegalBasis(str, Enum):
    LEGITIMATE_INTEREST = "legitimate_interest"
    CONTRACT = "contract"
    CONSENT = "consent"
    LEGAL_OBLIGATION = "legal_obligation"
    VITAL_INTERESTS = "vital_interests"
    PUBLIC_TASK = "public_task"
    OPERATOR_POLICY = "operator_policy"


class DataRightsGrant(BaseModel):
    """Canonical record for a data use permission grant.

    All boolean fields default to False (fail-closed).
    Grant creation is an explicit act; absence = denial.

    Default behaviors by connector class:
    - OLYMPUS_PROVIDER: olympus_baseline_allowed=True, model_training=False
    - TENANT_BYOD_DATA: tenant_lake_allowed=True, tenant_graph_allowed=True, rest False
    - BYOK_GATEWAY: no lake rights (credential control only)
    """
    data_rights_grant_id: str
    tenant_id: str
    contract_id: Optional[str] = None
    source_id: str
    connector_id: str
    connector_class: str
    source_manifest_id: Optional[str] = None
    data_category: str
    data_sensitivity: str
    raw_data_owner: str

    # ── Write permissions — all fail closed ──────────────────────────────────
    tenant_lake_allowed: bool = True
    tenant_graph_allowed: bool = True
    tenant_insights_allowed: bool = True
    olympus_baseline_allowed: bool = False
    cross_tenant_aggregate_allowed: bool = False
    model_training_allowed: bool = False
    commercial_reuse_allowed: bool = False

    # ── Policy metadata ───────────────────────────────────────────────────────
    legal_basis: str = LegalBasis.OPERATOR_POLICY.value
    consent_basis: Optional[str] = None
    granted_by_user_id: str
    granted_at: str
    expires_at: Optional[str] = None
    revoked_at: Optional[str] = None
    revocation_reason: Optional[str] = None
    status: GrantStatus = GrantStatus.ACTIVE
    audit_event_id: str

    # ── Olympus provider overrides (set on creation for Olympus sources) ──────
    # When connector_class == OLYMPUS_PROVIDER:
    #   olympus_baseline_allowed = True
    #   model_training_allowed = False (requires explicit compliance review)


class DataRightsGrantCreate(BaseModel):
    """Request body for creating a data rights grant."""
    tenant_id: str
    source_id: str
    connector_id: str
    connector_class: str
    source_manifest_id: Optional[str] = None
    data_category: str
    data_sensitivity: str = "unclassified"
    raw_data_owner: str
    tenant_lake_allowed: bool = True
    tenant_graph_allowed: bool = True
    tenant_insights_allowed: bool = True
    olympus_baseline_allowed: bool = False
    cross_tenant_aggregate_allowed: bool = False
    model_training_allowed: bool = False
    commercial_reuse_allowed: bool = False
    legal_basis: str = LegalBasis.OPERATOR_POLICY.value
    consent_basis: Optional[str] = None
    contract_id: Optional[str] = None
    expires_at: Optional[str] = None


class DataRightsGrantRevoke(BaseModel):
    """Request body for revoking a data rights grant."""
    revocation_reason: str
    revoked_by_user_id: str


class PolicyCheckResult(BaseModel):
    """Result of a fail-closed policy check."""
    grant_id: str
    check_type: str
    allowed: bool
    reason: str
    checked_at: str
    grant_status: GrantStatus


class PolicyCheckRequest(BaseModel):
    """Request to evaluate a specific policy check on a grant."""
    grant_id: str
    check_type: str  # olympus_baseline | model_training | cross_tenant_aggregate | commercial_reuse


class DataRightsGrantSummary(BaseModel):
    """Lightweight summary of a data rights grant (for list responses)."""
    data_rights_grant_id: str
    tenant_id: str
    source_id: str
    connector_id: str
    connector_class: str
    status: GrantStatus
    olympus_baseline_allowed: bool
    model_training_allowed: bool
    cross_tenant_aggregate_allowed: bool
    commercial_reuse_allowed: bool
    granted_at: str
    revoked_at: Optional[str] = None
