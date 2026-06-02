"""Policy Engine.

Evaluates governance policies and returns PolicyDecision records. For sensitive
decisions it persists the decision and writes a SecurityAuditEvent. Policies are
additive guardrails layered on top of existing OODA approval flows — they never
bypass them.

Supported policy keys:
  route.permission            recommendation.persist        decision.approve
  action.dispatch             action.elevated_dispatch       audit_export.create
  audit_export.download       kyber.operator_access          cross_tenant.access
  integration.configure       webhook.dispatch_safety        billing.admin_access
  data.deletion_request
"""
from __future__ import annotations

import ipaddress
from typing import Any, Optional
from urllib.parse import urlparse

from shared.logger.logger import get_logger

from .audit_ledger import audit_ledger
from .contracts import ActorType, PolicyDecision, PolicySeverity
from .repositories import PolicyDecisionRepository

logger = get_logger("aether.security.policy_engine")

# Policy keys whose decisions are always persisted + audited.
_SENSITIVE_KEYS = frozenset({
    "decision.approve", "action.dispatch", "action.elevated_dispatch",
    "audit_export.create", "audit_export.download", "kyber.operator_access",
    "cross_tenant.access", "integration.configure", "webhook.dispatch_safety",
    "billing.admin_access", "data.deletion_request",
})

# Hosts/ranges a webhook may never target (SSRF / metadata protection).
_BLOCKED_HOSTS = {"localhost", "metadata.google.internal"}


def _is_unsafe_destination(url: str) -> tuple[bool, str]:
    try:
        parsed = urlparse(url)
    except Exception:
        return True, "unparseable URL"
    if parsed.scheme not in ("https",):
        return True, f"scheme {parsed.scheme!r} not allowed (https required)"
    host = (parsed.hostname or "").lower()
    if not host:
        return True, "missing host"
    if host in _BLOCKED_HOSTS:
        return True, f"host {host!r} is blocked"
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return True, f"destination IP {host} is private/reserved"
    except ValueError:
        pass  # hostname, not a literal IP — allowed
    return False, "destination ok"


class PolicyEngine:
    def __init__(self, repo: Optional[PolicyDecisionRepository] = None) -> None:
        self._repo = repo or PolicyDecisionRepository()

    async def _finalize(
        self, decision: PolicyDecision, *, actor_type: ActorType,
        ip_address: Optional[str] = None, user_agent: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> PolicyDecision:
        if decision.policy_key in _SENSITIVE_KEYS or not decision.allowed:
            await self._repo.insert(decision.decision_id, decision.model_dump())
            await audit_ledger.record(
                actor_id=decision.actor_id, actor_type=actor_type,
                event_type=f"policy.{decision.policy_key}",
                resource_type=decision.resource_type, action=decision.action,
                outcome='allowed' if decision.allowed else 'blocked',
                tenant_id=decision.tenant_id, resource_id=decision.resource_id,
                policy_decision_id=decision.decision_id,
                ip_address=ip_address, user_agent=user_agent, metadata=metadata,
            )
        return decision

    def _decision(
        self, *, policy_key: str, actor_id: str, actor_type: ActorType, action: str,
        resource_type: str, allowed: bool, reason: str,
        severity: PolicySeverity = 'info', tenant_id: Optional[str] = None,
        resource_id: Optional[str] = None, required_action: Optional[str] = None,
    ) -> PolicyDecision:
        return PolicyDecision(
            tenant_id=tenant_id, actor_id=actor_id, actor_type=actor_type,
            policy_key=policy_key, resource_type=resource_type, resource_id=resource_id,
            action=action, allowed=allowed, reason=reason,
            severity=severity if not allowed else 'info',
            required_action=required_action,
        )

    # ── Specific policies ─────────────────────────────────────────────────────

    async def check_action_dispatch(
        self, *, actor_id: str, actor_type: ActorType, tenant_id: str,
        decision_status: str, action_id: Optional[str] = None,
        is_elevated: bool = False, approval_id: Optional[str] = None,
        **audit: Any,
    ) -> PolicyDecision:
        """Block dispatch unless the underlying decision is approved; block
        elevated/critical dispatch when no approval_id is present."""
        if decision_status != "approved":
            d = self._decision(
                policy_key="action.dispatch", actor_id=actor_id, actor_type=actor_type,
                action="dispatch", resource_type="action", tenant_id=tenant_id,
                resource_id=action_id, allowed=False, severity='block',
                reason=f"decision status is {decision_status!r}, not 'approved'",
                required_action="obtain decision approval before dispatch",
            )
            return await self._finalize(d, actor_type=actor_type, **audit)
        if is_elevated and not approval_id:
            d = self._decision(
                policy_key="action.elevated_dispatch", actor_id=actor_id,
                actor_type=actor_type, action="dispatch", resource_type="action",
                tenant_id=tenant_id, resource_id=action_id, allowed=False,
                severity='block', reason="elevated/critical dispatch requires approval_id",
                required_action="attach approval_id from human-in-the-loop approval",
            )
            return await self._finalize(d, actor_type=actor_type, **audit)
        d = self._decision(
            policy_key="action.dispatch", actor_id=actor_id, actor_type=actor_type,
            action="dispatch", resource_type="action", tenant_id=tenant_id,
            resource_id=action_id, allowed=True, reason="decision approved",
        )
        return await self._finalize(d, actor_type=actor_type, **audit)

    async def check_cross_tenant(
        self, *, actor_id: str, actor_type: ActorType, actor_tenant: Optional[str],
        target_tenant: str, resource_type: str, resource_id: Optional[str] = None,
        operator_authorized: bool = False, **audit: Any,
    ) -> PolicyDecision:
        """Block a tenant user from accessing another tenant's records; operators
        require explicit authorization (assigned role / break-glass)."""
        if actor_type == 'tenant_user' and actor_tenant != target_tenant:
            d = self._decision(
                policy_key="cross_tenant.access", actor_id=actor_id, actor_type=actor_type,
                action="read", resource_type=resource_type, tenant_id=target_tenant,
                resource_id=resource_id, allowed=False, severity='block',
                reason=f"tenant {actor_tenant!r} may not access tenant {target_tenant!r} records",
                required_action="access only your own tenant's data",
            )
            return await self._finalize(d, actor_type=actor_type, **audit)
        if actor_type == 'olympus_operator' and not operator_authorized:
            d = self._decision(
                policy_key="kyber.operator_access", actor_id=actor_id, actor_type=actor_type,
                action="read", resource_type=resource_type, tenant_id=target_tenant,
                resource_id=resource_id, allowed=False, severity='block',
                reason="operator lacks assigned role or active break-glass for this tenant",
                required_action="request break-glass access",
            )
            return await self._finalize(d, actor_type=actor_type, **audit)
        d = self._decision(
            policy_key="cross_tenant.access", actor_id=actor_id, actor_type=actor_type,
            action="read", resource_type=resource_type, tenant_id=target_tenant,
            resource_id=resource_id, allowed=True, reason="access authorized",
        )
        return await self._finalize(d, actor_type=actor_type, **audit)

    async def check_audit_export(
        self, *, actor_id: str, actor_type: ActorType, tenant_id: str,
        has_export_permission: bool, target_tenant: Optional[str] = None,
        sensitive: bool = False, approval_id: Optional[str] = None,
        operation: str = "create", **audit: Any,
    ) -> PolicyDecision:
        key = "audit_export.create" if operation == "create" else "audit_export.download"
        if not has_export_permission:
            d = self._decision(
                policy_key=key, actor_id=actor_id, actor_type=actor_type, action="export",
                resource_type="audit_export", tenant_id=tenant_id, allowed=False,
                severity='block', reason="missing audit_export export permission",
                required_action="request audit_export export permission",
            )
            return await self._finalize(d, actor_type=actor_type, **audit)
        if target_tenant and target_tenant != tenant_id and actor_type == 'tenant_user':
            d = self._decision(
                policy_key=key, actor_id=actor_id, actor_type=actor_type, action="export",
                resource_type="audit_export", tenant_id=tenant_id, allowed=False,
                severity='block', reason="cross-tenant audit export blocked",
            )
            return await self._finalize(d, actor_type=actor_type, **audit)
        if sensitive and not approval_id:
            d = self._decision(
                policy_key=key, actor_id=actor_id, actor_type=actor_type, action="export",
                resource_type="audit_export", tenant_id=tenant_id, allowed=False,
                severity='block', reason="sensitive export requires approval",
                required_action="obtain approval for high-risk export",
            )
            return await self._finalize(d, actor_type=actor_type, **audit)
        d = self._decision(
            policy_key=key, actor_id=actor_id, actor_type=actor_type, action="export",
            resource_type="audit_export", tenant_id=tenant_id, allowed=True,
            reason="export authorized",
        )
        return await self._finalize(d, actor_type=actor_type, **audit)

    async def check_integration_dispatch(
        self, *, actor_id: str, actor_type: ActorType, tenant_id: str,
        integration_enabled: bool, destination_url: Optional[str] = None,
        integration_id: Optional[str] = None, **audit: Any,
    ) -> PolicyDecision:
        if not integration_enabled:
            d = self._decision(
                policy_key="webhook.dispatch_safety", actor_id=actor_id, actor_type=actor_type,
                action="dispatch", resource_type="integration", tenant_id=tenant_id,
                resource_id=integration_id, allowed=False, severity='block',
                reason="integration is disabled",
            )
            return await self._finalize(d, actor_type=actor_type, **audit)
        if destination_url:
            unsafe, why = _is_unsafe_destination(destination_url)
            if unsafe:
                d = self._decision(
                    policy_key="webhook.dispatch_safety", actor_id=actor_id,
                    actor_type=actor_type, action="dispatch", resource_type="integration",
                    tenant_id=tenant_id, resource_id=integration_id, allowed=False,
                    severity='block', reason=f"unsafe webhook destination: {why}",
                )
                return await self._finalize(d, actor_type=actor_type, **audit)
        d = self._decision(
            policy_key="webhook.dispatch_safety", actor_id=actor_id, actor_type=actor_type,
            action="dispatch", resource_type="integration", tenant_id=tenant_id,
            resource_id=integration_id, allowed=True, reason="dispatch allowed",
        )
        return await self._finalize(d, actor_type=actor_type, **audit)

    async def check_data_deletion(
        self, *, actor_id: str, actor_type: ActorType, tenant_id: str,
        resource_type: str, has_manifest: bool = True, **audit: Any,
    ) -> PolicyDecision:
        if resource_type == "audit_log":
            d = self._decision(
                policy_key="data.deletion_request", actor_id=actor_id, actor_type=actor_type,
                action="delete", resource_type=resource_type, tenant_id=tenant_id,
                allowed=False, severity='block',
                reason="audit logs may not be deleted",
                required_action="audit logs are retained for security review",
            )
            return await self._finalize(d, actor_type=actor_type, **audit)
        if not has_manifest:
            d = self._decision(
                policy_key="data.deletion_request", actor_id=actor_id, actor_type=actor_type,
                action="delete", resource_type=resource_type, tenant_id=tenant_id,
                allowed=False, severity='block',
                reason="cross-resource deletion requires a manifest",
            )
            return await self._finalize(d, actor_type=actor_type, **audit)
        d = self._decision(
            policy_key="data.deletion_request", actor_id=actor_id, actor_type=actor_type,
            action="delete", resource_type=resource_type, tenant_id=tenant_id,
            allowed=True, reason="deletion request accepted for structured processing",
        )
        return await self._finalize(d, actor_type=actor_type, **audit)

    async def list_decisions(
        self, tenant_id: Optional[str] = None, limit: int = 100,
    ) -> list[dict]:
        if tenant_id:
            return await self._repo.list_for_tenant(tenant_id, limit=limit)
        return await self._repo.list_all(limit=limit)


policy_engine = PolicyEngine()
