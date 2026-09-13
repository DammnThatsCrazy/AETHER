"""Audit Export Governance.

Additive governance wrapper around audit-export creation/download. Enforces
export permission, blocks cross-tenant export, supports expiration + integrity
hash, a high-risk flag, and an approval requirement for sensitive export types.
Existing export producers continue to work; this layer governs them.
"""
from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Any, Optional

from shared.common.common import ForbiddenError, utc_now
from shared.logger.logger import get_logger

from .audit_ledger import audit_ledger
from .contracts import ActorType, now_iso, sanitize_metadata
from .policy_engine import policy_engine

logger = get_logger("aether.security.export_governance")

# Export types that require explicit approval before creation.
SENSITIVE_EXPORT_TYPES = frozenset({"full_audit_log", "cross_resource", "operator_access", "raw_events"})
DEFAULT_EXPIRY_DAYS = 7


def _integrity_hash(tenant_id: str, export_type: str, manifest: dict[str, Any]) -> str:
    import json
    payload = json.dumps(
        {"tenant_id": tenant_id, "export_type": export_type, "manifest": manifest},
        sort_keys=True, default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class AuditExportGovernance:
    async def authorize_create(
        self, *, actor_id: str, actor_type: ActorType, tenant_id: str,
        export_type: str, has_export_permission: bool,
        target_tenant: Optional[str] = None, approval_id: Optional[str] = None,
        manifest: Optional[dict[str, Any]] = None, ip_address: Optional[str] = None,
    ) -> dict[str, Any]:
        sensitive = export_type in SENSITIVE_EXPORT_TYPES
        decision = await policy_engine.check_audit_export(
            actor_id=actor_id, actor_type=actor_type, tenant_id=tenant_id,
            has_export_permission=has_export_permission, target_tenant=target_tenant,
            sensitive=sensitive, approval_id=approval_id, operation="create",
            ip_address=ip_address,
        )
        if not decision.allowed:
            raise ForbiddenError(decision.reason)
        manifest = sanitize_metadata(manifest or {})
        expires_at = (utc_now() + timedelta(days=DEFAULT_EXPIRY_DAYS)).isoformat()
        return {
            "tenant_id": tenant_id,
            "export_type": export_type,
            "high_risk": sensitive,
            "approval_id": approval_id,
            "integrity_hash": _integrity_hash(tenant_id, export_type, manifest),
            "expires_at": expires_at,
            "manifest": manifest,
            "created_at": now_iso(),
            "policy_decision_id": decision.decision_id,
        }

    async def authorize_download(
        self, *, actor_id: str, actor_type: ActorType, tenant_id: str,
        export_id: str, has_export_permission: bool, expires_at: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> None:
        if expires_at:
            try:
                from datetime import datetime
                if utc_now() >= datetime.fromisoformat(expires_at.replace("Z", "+00:00")):
                    await audit_ledger.record(
                        actor_id=actor_id, actor_type=actor_type,
                        event_type="audit_export.download_expired",
                        resource_type="audit_export", action="export",
                        outcome='blocked', tenant_id=tenant_id, resource_id=export_id,
                    )
                    raise ForbiddenError("audit export has expired")
            except ValueError:
                pass
        decision = await policy_engine.check_audit_export(
            actor_id=actor_id, actor_type=actor_type, tenant_id=tenant_id,
            has_export_permission=has_export_permission, operation="download",
            ip_address=ip_address,
        )
        if not decision.allowed:
            raise ForbiddenError(decision.reason)
        await audit_ledger.record(
            actor_id=actor_id, actor_type=actor_type,
            event_type="audit_export.download", resource_type="audit_export",
            action="export", outcome='allowed', tenant_id=tenant_id,
            resource_id=export_id, policy_decision_id=decision.decision_id,
            ip_address=ip_address,
        )


audit_export_governance = AuditExportGovernance()
