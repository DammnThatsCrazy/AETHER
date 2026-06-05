"""Pydantic contracts for the Security & Governance control plane.

Mirrors packages/shared/security-governance.ts field-for-field. No contract
field should ever carry a secret value — `sanitize_metadata` strips/redacts
secret-bearing keys before anything is persisted, logged, exported, or returned.
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from shared.common.common import utc_now

# ── Enums (as Literal unions, matching the TS string-literal unions) ──────────

AccessRole = Literal[
    'tenant_owner', 'tenant_admin', 'tenant_operator', 'tenant_analyst',
    'tenant_viewer', 'tenant_billing_admin', 'tenant_security_admin',
    'olympus_operator', 'olympus_support', 'olympus_admin', 'olympus_security',
    'olympus_revops', 'auditor',
]

GovernanceDomain = Literal[
    'profile', 'graph', 'recommendations', 'decisions', 'actions', 'dispatches',
    'outcomes', 'playbooks', 'integrations', 'audit_exports', 'billing',
    'onboarding', 'customer_success', 'kyber_admin', 'security', 'governance',
    'reliability', 'data_quality',
]

PermissionAction = Literal[
    'read', 'write', 'approve', 'dispatch', 'export', 'configure', 'delete', 'admin',
]

PermissionScope = Literal[
    'own_tenant', 'assigned_tenant', 'all_tenants_aggregate', 'all_tenants_admin',
]

ActorType = Literal['tenant_user', 'olympus_operator', 'system', 'agent']
PolicySeverity = Literal['info', 'warning', 'block']
SecurityAuditOutcome = Literal['allowed', 'blocked', 'failed']
BreakGlassStatus = Literal['requested', 'approved', 'denied', 'revoked', 'expired']

RetentionResourceType = Literal[
    'event', 'profile', 'recommendation', 'decision', 'action', 'dispatch',
    'outcome', 'audit_export', 'billing_record', 'audit_log',
]
RetentionDeleteBehavior = Literal[
    'hard_delete', 'soft_delete', 'anonymize', 'preserve_audit_stub',
]
DataRequestType = Literal[
    'export', 'delete_entity', 'delete_tenant', 'retention_review', 'access_review',
]
DataRequestStatus = Literal[
    'requested', 'in_progress', 'completed', 'denied', 'failed',
]
EvidencePackType = Literal[
    'access_control', 'tenant_isolation', 'audit_logging', 'data_retention',
    'integration_security', 'ai_recommendation_governance', 'operator_access',
]
EvidencePackStatus = Literal['queued', 'generated', 'failed', 'expired']


# ── Secret hygiene (same pattern as services/billing/revops.py) ───────────────

SECRET_RE = re.compile(
    r"(api[_-]?key|secret|token|password|authorization|credential|"
    r"private[_-]?key|signing[_-]?secret|bearer|access[_-]?key)",
    re.I,
)


def now_iso() -> str:
    return utc_now().isoformat()


def sanitize_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Recursively drop secret-named keys and redact secret-looking values.

    Used before persisting any audit metadata, policy reason, export payload,
    or evidence pack so secrets never reach storage, logs, exports, or the UI.
    """
    cleaned: dict[str, Any] = {}
    for key, value in (metadata or {}).items():
        if SECRET_RE.search(str(key)):
            continue
        if isinstance(value, str) and SECRET_RE.search(value[:120]):
            cleaned[key] = '[redacted]'
        elif isinstance(value, dict):
            cleaned[key] = sanitize_metadata(value)
        elif isinstance(value, list):
            cleaned[key] = [
                sanitize_metadata(v) if isinstance(v, dict) else v for v in value
            ]
        else:
            cleaned[key] = value
    return cleaned


# ── Contracts ─────────────────────────────────────────────────────────────────

class PermissionGrant(BaseModel):
    permission_id: str = Field(default_factory=lambda: f"perm_{uuid.uuid4().hex}")
    role: AccessRole
    domain: GovernanceDomain
    action: PermissionAction
    scope: PermissionScope
    created_at: str = Field(default_factory=now_iso)


class PolicyDecision(BaseModel):
    decision_id: str = Field(default_factory=lambda: f"pdec_{uuid.uuid4().hex}")
    tenant_id: Optional[str] = None
    actor_id: str
    actor_type: ActorType
    policy_key: str
    resource_type: str
    resource_id: Optional[str] = None
    action: str
    allowed: bool
    reason: str
    severity: PolicySeverity = 'info'
    required_action: Optional[str] = None
    evaluated_at: str = Field(default_factory=now_iso)


class SecurityAuditEvent(BaseModel):
    audit_event_id: str = Field(default_factory=lambda: f"audit_{uuid.uuid4().hex}")
    tenant_id: Optional[str] = None
    actor_id: str
    actor_type: ActorType
    event_type: str
    resource_type: str
    resource_id: Optional[str] = None
    action: str
    outcome: SecurityAuditOutcome
    policy_decision_id: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None
    integrity_hash: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)


class BreakGlassRequest(BaseModel):
    request_id: str = Field(default_factory=lambda: f"bg_{uuid.uuid4().hex}")
    tenant_id: str
    requested_by: str
    approved_by: Optional[str] = None
    reason: str
    requested_scope: str
    status: BreakGlassStatus = 'requested'
    starts_at: Optional[str] = None
    expires_at: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class DataRetentionPolicy(BaseModel):
    policy_id: str = Field(default_factory=lambda: f"retpol_{uuid.uuid4().hex}")
    tenant_id: Optional[str] = None
    resource_type: RetentionResourceType
    retention_days: int = 365
    legal_hold_supported: bool = True
    delete_behavior: RetentionDeleteBehavior = 'soft_delete'
    enabled: bool = True
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class DataRequest(BaseModel):
    data_request_id: str = Field(default_factory=lambda: f"datareq_{uuid.uuid4().hex}")
    tenant_id: str
    request_type: DataRequestType
    requested_by: str
    status: DataRequestStatus = 'requested'
    target_resource_type: Optional[str] = None
    target_resource_id: Optional[str] = None
    result_summary: Optional[str] = None
    created_at: str = Field(default_factory=now_iso)
    completed_at: Optional[str] = None


class GovernanceEvidencePack(BaseModel):
    evidence_pack_id: str = Field(default_factory=lambda: f"evpack_{uuid.uuid4().hex}")
    tenant_id: Optional[str] = None
    pack_type: EvidencePackType
    status: EvidencePackStatus = 'queued'
    included_controls: list[str] = Field(default_factory=list)
    known_gaps: list[str] = Field(default_factory=list)
    file_ref: Optional[str] = None
    integrity_hash: Optional[str] = None
    requested_by: str
    generated_at: Optional[str] = None
    expires_at: Optional[str] = None
