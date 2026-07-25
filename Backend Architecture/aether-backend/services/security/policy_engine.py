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
  data.deletion_request       capability.invoke              kyber.access
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
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
    "billing.admin_access", "data.deletion_request", "capability.invoke",
    "kyber.access",
})

# Hosts/ranges a webhook may never target (SSRF / metadata protection).
_BLOCKED_HOSTS = {"localhost", "metadata.google.internal"}


def _ip_is_unsafe(ip: ipaddress._BaseAddress) -> bool:
    """True if an IP must never be a webhook destination (SSRF / metadata)."""
    return (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    )


def _resolve_host(host: str) -> list[str]:
    """Resolve a hostname to its IP addresses. Patchable in tests.

    Raises socket.gaierror (or OSError) when the name does not resolve.
    """
    infos = socket.getaddrinfo(host, None)
    return sorted({info[4][0] for info in infos})


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
    # Literal IP: check directly.
    try:
        ip = ipaddress.ip_address(host)
        if _ip_is_unsafe(ip):
            return True, f"destination IP {host} is private/reserved"
        return False, "destination ok"
    except ValueError:
        pass  # not a literal IP — resolve the hostname below
    # Hostname: resolve it and reject if ANY resolved address is unsafe. A name
    # that does not resolve is rejected (fail-closed) so internal-only or
    # DNS-rebinding hostnames cannot slip past the literal-IP guard.
    try:
        addrs = _resolve_host(host)
    except (socket.gaierror, OSError):
        return True, f"destination host {host!r} could not be resolved"
    if not addrs:
        return True, f"destination host {host!r} did not resolve to any address"
    for addr in addrs:
        try:
            if _ip_is_unsafe(ipaddress.ip_address(addr)):
                return True, f"host {host!r} resolves to private/reserved address {addr}"
        except ValueError:
            return True, f"host {host!r} resolved to an unparseable address {addr!r}"
    return False, "destination ok"


DNS_RESOLVE_TIMEOUT_S = 5.0


async def evaluate_destination_safety(url: str, timeout: float = DNS_RESOLVE_TIMEOUT_S) -> tuple[bool, str]:
    """Async wrapper around `_is_unsafe_destination`.

    `_is_unsafe_destination` performs a synchronous, potentially slow DNS lookup;
    running it directly inside an async request handler would block the event
    loop. Offload it to a bounded threadpool with a timeout, and fail-closed
    (treat as unsafe) if the resolver is slow/wedged.
    """
    try:
        return await asyncio.wait_for(asyncio.to_thread(_is_unsafe_destination, url), timeout)
    except asyncio.TimeoutError:
        return True, "destination safety check timed out"


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

    async def check_kyber_access(
        self, *, actor_id: str, operator_id: Optional[str], session_id: Optional[str],
        device_id: Optional[str], capability: str, action_class: int, route_id: str,
        environment: str, target_tenant: Optional[str], purpose: Optional[str],
        requested_disclosure: Optional[str], granted_disclosure: Optional[str],
        allowed: bool, denial_reason: Optional[str] = None,
        step_up_required: bool = False, approval_required: bool = False,
        ip_address: Optional[str] = None, user_agent: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> PolicyDecision:
        """Record a Kyber workforce access decision as a first-class policy decision.

        The Kyber access plane (capability + disclosure + tenant scope + device +
        session strength) is evaluated by ``services.kyber.access.dependencies``;
        this method is where the RESULT becomes evidence. It deliberately does
        not re-evaluate authority: a second, divergent copy of the rules is
        exactly the failure this design avoids.

        ``kyber.access`` is a sensitive policy key, so allowed decisions are
        persisted alongside denials — an operator access log that only records
        refusals is not an access log. Persistence runs through the shared
        ``_finalize`` path, so the decision lands in ``security_policy_decisions``
        and a linked ``audit_ledger`` entry is written; there is no second table
        and no second ledger.

        ``target_tenant`` becomes the decision's ``tenant_id`` so a tenant's
        operator-access history is queryable by tenant, exactly like
        ``cross_tenant.access``.
        """
        actor_type: ActorType = 'olympus_operator'
        meta = dict(metadata or {})
        meta.update({
            "capability": capability,
            "action_class": action_class,
            "route_id": route_id,
            "environment": environment,
            "operator_id": operator_id,
            # Named `*_ref`, not `session_id`/`device_id` wholesale: these are
            # opaque handles that belong in the evidence trail, and keeping the
            # explicit keys makes a decision reconstructable from the ledger.
            "session_ref": session_id,
            "device_ref": device_id,
            "purpose": purpose,
            "requested_disclosure": requested_disclosure,
            "granted_disclosure": granted_disclosure,
            "step_up_required": step_up_required,
            "approval_required": approval_required,
        })

        if allowed:
            reason = "kyber access authorized"
            required_action = None
        else:
            reason = denial_reason or f"capability {capability!r} not authorized"
            required_action = None
            if step_up_required:
                required_action = "complete step-up authentication"
            elif approval_required:
                required_action = "obtain approval for this action"
            elif target_tenant:
                required_action = "request a purpose-bound tenant access scope"

        decision = self._decision(
            policy_key="kyber.access", actor_id=actor_id, actor_type=actor_type,
            action=capability, resource_type="kyber_route", resource_id=route_id,
            tenant_id=target_tenant, allowed=allowed, reason=reason,
            severity='info' if allowed else 'block', required_action=required_action,
        )
        return await self._finalize(
            decision, actor_type=actor_type,
            ip_address=ip_address, user_agent=user_agent, metadata=meta,
        )

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
            unsafe, why = await evaluate_destination_safety(destination_url)
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

    async def check_capability_invocation(
        self, *, actor_id: str, actor_type: ActorType, tenant_id: str,
        capability_id: str, agent_id: Optional[str] = None,
        capability_observed: bool = False, has_active_authorization: bool = False,
        authorization_id: Optional[str] = None, latest_risk_level: Optional[str] = None,
        **audit: Any,
    ) -> PolicyDecision:
        """Decide whether an agent may invoke an observed external capability.

        Inputs are pre-resolved facts (mirroring every other policy here, which takes
        booleans rather than doing its own I/O) — ``CapabilityAuthorityService.resolve``
        supplies them. That keeps the security package free of an Agent Access
        Intelligence import and keeps this the platform's only policy engine.

        ``capability.invoke`` is a sensitive key, so *every* decision — allow included —
        is persisted to ``security_policy_decisions`` and written to the audit ledger.
        That persistence is what makes the decision log a real record rather than a
        deny-only sample.

        ``latest_risk_level`` deliberately does **not** change the verdict. No policy
        source in this repo defines a risk threshold that blocks invocation, and
        inventing one here would be a fabricated control that operators would reasonably
        believe is enforced. Risk travels in the audit metadata; risk-driven findings
        are a separate, explicit surface.
        """
        meta = dict(audit.pop("metadata", None) or {})
        meta.update({
            "capability_id": capability_id,
            "agent_id": agent_id,
            "capability_observed": capability_observed,
            "latest_risk_level": latest_risk_level,
            # Named `capability_grant_id`, not `authorization_id`: contracts.SECRET_RE
            # matches the substring "authorization" and sanitize_metadata DROPS any key
            # it matches, so an `authorization_id` key would silently vanish from the
            # ledger and the evidence log would never record *which* grant permitted the
            # invocation. The sanitizer is correct and is not weakened; the key is renamed.
            "capability_grant_id": authorization_id,
        })

        def _deny(reason: str, required_action: str) -> PolicyDecision:
            return self._decision(
                policy_key="capability.invoke", actor_id=actor_id, actor_type=actor_type,
                action="invoke", resource_type="capability", tenant_id=tenant_id,
                resource_id=capability_id, allowed=False, severity='block',
                reason=reason, required_action=required_action,
            )

        if not capability_observed:
            return await self._finalize(
                _deny(
                    "capability not in tenant inventory",
                    "observe or authorize it explicitly before invocation",
                ),
                actor_type=actor_type, metadata=meta, **audit,
            )
        if not agent_id:
            return await self._finalize(
                _deny(
                    "invoking agent is unidentified",
                    "attribute the invocation to an agent",
                ),
                actor_type=actor_type, metadata=meta, **audit,
            )
        if not has_active_authorization:
            return await self._finalize(
                _deny(
                    "no active capability authorization",
                    "grant one via POST /v1/capability-authorizations",
                ),
                actor_type=actor_type, metadata=meta, **audit,
            )
        d = self._decision(
            policy_key="capability.invoke", actor_id=actor_id, actor_type=actor_type,
            action="invoke", resource_type="capability", tenant_id=tenant_id,
            resource_id=capability_id, allowed=True,
            reason="active capability authorization",
        )
        return await self._finalize(d, actor_type=actor_type, metadata=meta, **audit)

    async def list_decisions(
        self, tenant_id: Optional[str] = None, limit: int = 100,
        policy_key: Optional[str] = None,
    ) -> list[dict]:
        # `policy_key` filters in the query rather than after the fact: a caller that
        # wants one policy's log must not receive an empty page merely because the
        # tenant's most recent `limit` decisions belong to other policies.
        extra = {"policy_key": policy_key} if policy_key else None
        if tenant_id:
            return await self._repo.list_for_tenant(tenant_id, limit=limit, extra=extra)
        return await self._repo.list_all(limit=limit, extra=extra)


policy_engine = PolicyEngine()
