"""
Agentic Provider Framework — adapter protocol, provider registry, permission findings.

INVARIANT: All adapter operations are READ-ONLY reference operations.
           AETHER never writes to, executes against, or mutates external provider state.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Protocol, runtime_checkable

from shared.logger.logger import get_logger

logger = get_logger("aether.agentic_observability.provider_framework")


class ProviderVerificationStatus(str, Enum):
    CONFIRMED = "confirmed"
    CONTRADICTED = "contradicted"
    UNVERIFIED = "unverified"
    PENDING = "pending"
    EXPIRED = "expired"
    REVOKED = "revoked"
    INSUFFICIENT_DATA = "insufficient_data"


PROVIDER_TRUTH_PRECEDENCE = (
    ProviderVerificationStatus.CONFIRMED,
    ProviderVerificationStatus.CONTRADICTED,
    ProviderVerificationStatus.UNVERIFIED,
    ProviderVerificationStatus.PENDING,
    ProviderVerificationStatus.EXPIRED,
    ProviderVerificationStatus.REVOKED,
    ProviderVerificationStatus.INSUFFICIENT_DATA,
)


@dataclass
class ProviderMetadata:
    provider_id: str
    name: str
    description: str
    read_only: bool = True
    supported_operations: list[str] = field(default_factory=list)
    webhook_supported: bool = False


@dataclass
class ExternalAccountRecord:
    account_id: str
    provider_id: str
    tenant_id: str
    external_account_id: str
    account_type: Optional[str] = None
    display_name: Optional[str] = None
    scopes: list[str] = field(default_factory=list)
    observed_at: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AuthorizationGrantRecord:
    grant_id: str
    tenant_id: str
    provider_id: str
    agent_id: Optional[str] = None
    scopes: list[str] = field(default_factory=list)
    granted_at: Optional[str] = None
    expires_at: Optional[str] = None
    revoked_at: Optional[str] = None
    is_active: bool = True

    @property
    def scope_hash(self) -> str:
        return hashlib.sha256(",".join(sorted(self.scopes)).encode()).hexdigest()[:16]


@dataclass
class ProviderActionRecord:
    action_id: str
    provider_id: str
    agent_id: Optional[str] = None
    action_type: str = "unknown"
    scopes_used: list[str] = field(default_factory=list)
    observed_at: Optional[str] = None
    outcome: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExternalObjectRecord:
    object_id: str
    provider_id: str
    object_type: str
    external_object_id: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderVerificationRecord:
    verification_id: str
    provider_id: str
    action_id: Optional[str] = None
    status: ProviderVerificationStatus = ProviderVerificationStatus.UNVERIFIED
    verified_at: Optional[str] = None
    method: str = "webhook"
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class PermissionFinding:
    finding_type: str
    severity: str
    description: str
    grant_id: Optional[str] = None
    agent_id: Optional[str] = None
    scopes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderHealthRecord:
    provider_id: str
    healthy: bool
    latency_ms: Optional[float] = None
    error: Optional[str] = None
    checked_at: Optional[str] = None


@runtime_checkable
class AgenticProviderAdapter(Protocol):
    @property
    def metadata(self) -> ProviderMetadata: ...
    def normalize_account(self, raw: dict[str, Any]) -> ExternalAccountRecord: ...
    def normalize_authorization(self, raw: dict[str, Any]) -> AuthorizationGrantRecord: ...
    def normalize_action(self, raw: dict[str, Any]) -> ProviderActionRecord: ...
    def normalize_object(self, raw: dict[str, Any]) -> ExternalObjectRecord: ...
    def verify_action(self, action: ProviderActionRecord, provider_snapshot: dict[str, Any]) -> ProviderVerificationRecord: ...
    def consume_webhook(self, tenant_id: str, body: bytes, headers: dict[str, str], secret: str) -> dict[str, Any]: ...
    def health_check(self) -> ProviderHealthRecord: ...


class XReferenceAdapter:
    """Read-only X reference adapter. Normalizes X (Twitter) account/auth/action observations."""

    @property
    def metadata(self) -> ProviderMetadata:
        return ProviderMetadata(
            provider_id="x_reference",
            name="X (Twitter) Reference Adapter",
            description="Read-only observation adapter for X platform activity",
            read_only=True,
            supported_operations=["account_lookup", "auth_verification", "action_observation"],
            webhook_supported=True,
        )

    def normalize_account(self, raw: dict[str, Any]) -> ExternalAccountRecord:
        return ExternalAccountRecord(
            account_id=raw.get("id", ""),
            provider_id="x_reference",
            tenant_id=raw.get("tenant_id", ""),
            external_account_id=raw.get("external_user_id", raw.get("username", "")),
            account_type="x_user",
            display_name=raw.get("name") or raw.get("username"),
            scopes=raw.get("scopes", []),
            observed_at=raw.get("observed_at"),
            metadata={k: v for k, v in raw.items() if k not in {"id", "tenant_id"}},
        )

    def normalize_authorization(self, raw: dict[str, Any]) -> AuthorizationGrantRecord:
        return AuthorizationGrantRecord(
            grant_id=raw.get("grant_id", ""),
            tenant_id=raw.get("tenant_id", ""),
            provider_id="x_reference",
            agent_id=raw.get("agent_id"),
            scopes=raw.get("scopes", []),
            granted_at=raw.get("granted_at"),
            expires_at=raw.get("expires_at"),
            revoked_at=raw.get("revoked_at"),
            is_active=raw.get("is_active", True),
        )

    def normalize_action(self, raw: dict[str, Any]) -> ProviderActionRecord:
        return ProviderActionRecord(
            action_id=raw.get("action_id", ""),
            provider_id="x_reference",
            agent_id=raw.get("agent_id"),
            action_type=raw.get("action_type", "unknown"),
            scopes_used=raw.get("scopes_used", []),
            observed_at=raw.get("observed_at"),
            outcome=raw.get("outcome"),
            metadata={k: v for k, v in raw.items() if k not in {"action_id", "agent_id"}},
        )

    def normalize_object(self, raw: dict[str, Any]) -> ExternalObjectRecord:
        return ExternalObjectRecord(
            object_id=raw.get("object_id", ""),
            provider_id="x_reference",
            object_type=raw.get("object_type", "post"),
            external_object_id=raw.get("external_id"),
            metadata=raw,
        )

    def verify_action(
        self, action: ProviderActionRecord, provider_snapshot: dict[str, Any]
    ) -> ProviderVerificationRecord:
        from shared.common.common import utc_now
        snapshot_actions = provider_snapshot.get("actions", [])
        matched = any(a.get("action_id") == action.action_id for a in snapshot_actions)
        status = ProviderVerificationStatus.CONFIRMED if matched else ProviderVerificationStatus.UNVERIFIED
        return ProviderVerificationRecord(
            verification_id=str(uuid.uuid4()),
            provider_id="x_reference",
            action_id=action.action_id,
            status=status,
            verified_at=utc_now().isoformat(),
            method="provider_snapshot_comparison",
            evidence={"snapshot_action_count": len(snapshot_actions), "matched": matched},
        )

    def consume_webhook(
        self, tenant_id: str, body: bytes, headers: dict[str, str], secret: str
    ) -> dict[str, Any]:
        sig_header = headers.get("x-twitter-signature") or headers.get("x-signature", "")
        if secret and sig_header:
            expected = "sha256=" + hmac.new(secret.encode(), body, "sha256").hexdigest()
            if not hmac.compare_digest(sig_header, expected):
                raise ValueError("HMAC signature mismatch — webhook rejected")
        try:
            payload = json.loads(body)
        except Exception:
            raise ValueError("Invalid webhook body — JSON parse failed")
        return {"tenant_id": tenant_id, "raw": payload, "provider": "x_reference"}

    def health_check(self) -> ProviderHealthRecord:
        from shared.common.common import utc_now
        return ProviderHealthRecord(
            provider_id="x_reference",
            healthy=True,
            latency_ms=None,
            checked_at=utc_now().isoformat(),
        )


class ProviderRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, Any] = {}

    def register(self, adapter: Any) -> None:
        self._adapters[adapter.metadata.provider_id] = adapter

    def get(self, provider_id: str) -> Optional[Any]:
        return self._adapters.get(provider_id)

    def list_metadata(self) -> list[ProviderMetadata]:
        return [a.metadata for a in self._adapters.values()]


def compute_permission_findings(
    tenant_id: str,
    grants: list[AuthorizationGrantRecord],
    actions: list[ProviderActionRecord],
    approved_scope_baselines: dict[str, list[str]],
) -> list[PermissionFinding]:
    findings: list[PermissionFinding] = []
    from shared.common.common import utc_now

    now_str = utc_now().isoformat()

    for grant in grants:
        if grant.expires_at and grant.expires_at < now_str and grant.is_active:
            findings.append(PermissionFinding(
                finding_type="expired_grant",
                severity="medium",
                description=f"Grant {grant.grant_id} is past its expiry but still marked active",
                grant_id=grant.grant_id,
                agent_id=grant.agent_id,
                scopes=grant.scopes,
            ))

        if grant.revoked_at:
            for action in actions:
                if (action.agent_id == grant.agent_id
                        and action.observed_at
                        and action.observed_at > grant.revoked_at):
                    findings.append(PermissionFinding(
                        finding_type="revoked_grant_used",
                        severity="high",
                        description=f"Action {action.action_id} used revoked grant {grant.grant_id}",
                        grant_id=grant.grant_id,
                        agent_id=grant.agent_id,
                        scopes=action.scopes_used,
                    ))

        baseline = approved_scope_baselines.get(grant.grant_id, [])
        unexpected = [s for s in grant.scopes if s not in baseline]
        if unexpected:
            findings.append(PermissionFinding(
                finding_type="unexpected_new_scope",
                severity="medium",
                description=f"Grant {grant.grant_id} has scopes not in approved baseline: {unexpected}",
                grant_id=grant.grant_id,
                scopes=unexpected,
            ))

        used_scopes: set[str] = set()
        for action in actions:
            if action.agent_id == grant.agent_id:
                used_scopes.update(action.scopes_used)
        write_scopes = [s for s in grant.scopes if "write" in s or "post" in s or "delete" in s]
        unused_writes = [s for s in write_scopes if s not in used_scopes]
        if unused_writes:
            findings.append(PermissionFinding(
                finding_type="write_scope_unused",
                severity="low",
                description=f"Grant {grant.grant_id} has unused write scopes: {unused_writes}",
                grant_id=grant.grant_id,
                scopes=unused_writes,
            ))

    return findings


def build_provider_graph_projection(
    account: ExternalAccountRecord,
    grant: AuthorizationGrantRecord,
    action: ProviderActionRecord,
    verification: ProviderVerificationRecord,
) -> list[dict[str, Any]]:
    """Build vertex/edge projection records without writing to the graph."""
    nodes: list[dict[str, Any]] = []
    nodes.append({
        "type": "vertex",
        "vertex_id": f"account:{account.account_id}",
        "label": "ExternalAccount",
        "properties": {
            "provider_id": account.provider_id,
            "external_account_id": account.external_account_id,
            "tenant_id": account.tenant_id,
        },
    })
    nodes.append({
        "type": "vertex",
        "vertex_id": f"grant:{grant.grant_id}",
        "label": "AuthorizationGrant",
        "properties": {
            "provider_id": grant.provider_id,
            "agent_id": grant.agent_id,
            "scope_hash": grant.scope_hash,
            "tenant_id": grant.tenant_id,
        },
    })
    nodes.append({
        "type": "edge",
        "from_vertex": f"account:{account.account_id}",
        "to_vertex": f"grant:{grant.grant_id}",
        "label": "has_grant",
        "properties": {"tenant_id": account.tenant_id},
    })
    nodes.append({
        "type": "vertex",
        "vertex_id": f"action:{action.action_id}",
        "label": "ProviderAction",
        "properties": {
            "action_type": action.action_type,
            "provider_id": action.provider_id,
            "verification_status": verification.status.value,
        },
    })
    nodes.append({
        "type": "edge",
        "from_vertex": f"grant:{grant.grant_id}",
        "to_vertex": f"action:{action.action_id}",
        "label": "authorized_action",
        "properties": {"tenant_id": account.tenant_id},
    })
    return nodes


provider_registry = ProviderRegistry()
provider_registry.register(XReferenceAdapter())
