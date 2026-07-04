"""Provider-neutral delegated authorization and verification framework.

The framework is intentionally observation-only. Adapter methods normalize or verify
externally observed data that was supplied by a webhook, read-only provider API
response, or connector backfill. They must not execute provider writes, submit
provider requests, sign provider payloads, post content, trade, settle, revoke
access, or custody raw credentials.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import hmac
import json
from typing import Any, Mapping, Protocol, Sequence


class ProviderVerificationStatus(str, Enum):
    UNVERIFIED = "unverified"
    RUNTIME_OBSERVED = "runtime_observed"
    GATEWAY_OBSERVED = "gateway_observed"
    SERVER_CONFIRMED = "server_confirmed"
    PROVIDER_CONFIRMED = "provider_confirmed"
    CONTRADICTED = "contradicted"
    RECONCILED = "reconciled"
    VERIFICATION_EXPIRED = "verification_expired"


PROVIDER_TRUTH_PRECEDENCE: tuple[str, ...] = (
    "provider_webhook",
    "provider_api_read",
    "mcp_server_response",
    "aether_gateway_observation",
    "agent_runtime_self_report",
    "derived_inference",
)


@dataclass(frozen=True, slots=True)
class ProviderMetadata:
    provider_id: str
    provider_name: str
    connector_version: str
    supported_events: tuple[str, ...]
    required_scopes: tuple[str, ...] = ()
    optional_scopes: tuple[str, ...] = ()
    webhook_support: bool = False
    backfill_support: bool = False
    verification_support: bool = True
    content_policy: str = "metadata_only"
    rate_limit_policy: str = "read_only_provider_limits"
    status: str = "available"


@dataclass(frozen=True, slots=True)
class ExternalAccountRecord:
    tenant_id: str
    provider_id: str
    external_account_id: str
    account_handle: str | None = None
    workspace_id: str | None = None
    observed_at: str | None = None
    evidence_ref: str | None = None


@dataclass(frozen=True, slots=True)
class AuthorizationGrantRecord:
    tenant_id: str
    provider_id: str
    authorization_id: str
    external_account_id: str
    grantee_id: str | None = None
    grantor_id: str | None = None
    scopes: tuple[str, ...] = ()
    credential_ref: str | None = None
    approved_at: str | None = None
    expires_at: str | None = None
    revoked_at: str | None = None
    evidence_ref: str | None = None

    @property
    def scope_hash(self) -> str:
        return sha256("\n".join(sorted(self.scopes)).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ProviderActionRecord:
    tenant_id: str
    provider_id: str
    provider_action_id: str
    action_type: str
    provider_request_id: str | None = None
    external_object_id: str | None = None
    authorization_id: str | None = None
    external_account_id: str | None = None
    observed_at: str | None = None
    evidence_ref: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExternalObjectRecord:
    tenant_id: str
    provider_id: str
    external_object_id: str
    object_type: str
    object_url: str | None = None
    observed_at: str | None = None
    evidence_ref: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderVerificationRecord:
    tenant_id: str
    provider_id: str
    provider_action_id: str
    verification_status: ProviderVerificationStatus
    verification_source: str
    confidence: float
    verified_at: str
    provider_request_id: str | None = None
    external_object_id: str | None = None
    evidence_ref: str | None = None
    contradiction_reason: str | None = None


@dataclass(frozen=True, slots=True)
class PermissionFinding:
    tenant_id: str
    finding_type: str
    severity: str
    reason_codes: tuple[str, ...]
    affected_entities: tuple[str, ...]
    evidence_refs: tuple[str, ...] = ()
    recommended_action: str = "review_with_human_owner"


@dataclass(frozen=True, slots=True)
class ProviderHealthRecord:
    provider_id: str
    status: str
    checked_at: str
    api_success_rate: float = 1.0
    webhook_freshness_seconds: int | None = None
    verification_delay_seconds: int | None = None
    reconciliation_backlog: int = 0
    rate_limit_state: str = "unknown"


class AgenticProviderAdapter(Protocol):
    metadata: ProviderMetadata

    def normalize_account(self, tenant_id: str, payload: Mapping[str, Any]) -> ExternalAccountRecord: ...

    def normalize_authorization(self, tenant_id: str, payload: Mapping[str, Any]) -> AuthorizationGrantRecord: ...

    def normalize_action(self, tenant_id: str, payload: Mapping[str, Any]) -> ProviderActionRecord: ...

    def normalize_object(self, tenant_id: str, payload: Mapping[str, Any]) -> ExternalObjectRecord: ...

    def verify_action(self, action: ProviderActionRecord, provider_snapshot: Mapping[str, Any] | None) -> ProviderVerificationRecord: ...

    def consume_webhook(self, tenant_id: str, body: bytes, headers: Mapping[str, str], secret: str | None = None) -> list[ProviderVerificationRecord]: ...

    def health_check(self) -> ProviderHealthRecord: ...


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def stable_ref(*parts: str | None) -> str:
    return sha256("|".join(part or "" for part in parts).encode("utf-8")).hexdigest()


class ProviderRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, AgenticProviderAdapter] = {}

    def register(self, adapter: AgenticProviderAdapter) -> None:
        self._adapters[adapter.metadata.provider_id] = adapter

    def get(self, provider_id: str) -> AgenticProviderAdapter:
        try:
            return self._adapters[provider_id]
        except KeyError as exc:
            raise KeyError(f"unknown provider adapter: {provider_id}") from exc

    def list_metadata(self) -> list[ProviderMetadata]:
        return sorted((adapter.metadata for adapter in self._adapters.values()), key=lambda item: item.provider_id)


class XReferenceAdapter:
    """Read-only X reference adapter for provider verification.

    The adapter only normalizes externally supplied account/action snapshots and
    verifies actions against read-only provider evidence. It deliberately has no
    write methods for creating posts, replies, follows, messages, or deletions.
    """

    metadata = ProviderMetadata(
        provider_id="x",
        provider_name="X",
        connector_version="2026.07.0",
        supported_events=(
            "content_created",
            "content_updated",
            "content_deleted",
            "reply_created",
            "engagement_observed",
            "link_clicked",
            "provider_error",
            "permission_denial",
            "rate_limit_denial",
        ),
        required_scopes=("tweet.read", "users.read"),
        optional_scopes=("tweet.write", "offline.access"),
        webhook_support=True,
        backfill_support=True,
        verification_support=True,
    )

    def normalize_account(self, tenant_id: str, payload: Mapping[str, Any]) -> ExternalAccountRecord:
        external_account_id = str(payload["external_account_id"])
        return ExternalAccountRecord(
            tenant_id=tenant_id,
            provider_id=self.metadata.provider_id,
            external_account_id=external_account_id,
            account_handle=payload.get("handle") or payload.get("username"),
            workspace_id=payload.get("workspace_id"),
            observed_at=payload.get("observed_at") or utc_now(),
            evidence_ref=payload.get("evidence_ref") or f"evidence:x:account:{external_account_id}",
        )

    def normalize_authorization(self, tenant_id: str, payload: Mapping[str, Any]) -> AuthorizationGrantRecord:
        scopes = tuple(sorted(str(scope) for scope in payload.get("scopes", ())))
        return AuthorizationGrantRecord(
            tenant_id=tenant_id,
            provider_id=self.metadata.provider_id,
            authorization_id=str(payload["authorization_id"]),
            external_account_id=str(payload["external_account_id"]),
            grantee_id=payload.get("grantee_id"),
            grantor_id=payload.get("grantor_id"),
            scopes=scopes,
            credential_ref=payload.get("credential_ref"),
            approved_at=payload.get("approved_at"),
            expires_at=payload.get("expires_at"),
            revoked_at=payload.get("revoked_at"),
            evidence_ref=payload.get("evidence_ref"),
        )

    def normalize_action(self, tenant_id: str, payload: Mapping[str, Any]) -> ProviderActionRecord:
        provider_action_id = str(payload.get("provider_action_id") or stable_ref(tenant_id, payload.get("provider_request_id"), payload.get("external_object_id")))
        return ProviderActionRecord(
            tenant_id=tenant_id,
            provider_id=self.metadata.provider_id,
            provider_action_id=provider_action_id,
            action_type=str(payload["action_type"]),
            provider_request_id=payload.get("provider_request_id"),
            external_object_id=payload.get("external_object_id"),
            authorization_id=payload.get("authorization_id"),
            external_account_id=payload.get("external_account_id"),
            observed_at=payload.get("observed_at") or utc_now(),
            evidence_ref=payload.get("evidence_ref"),
            metadata=dict(payload.get("metadata") or {}),
        )

    def normalize_object(self, tenant_id: str, payload: Mapping[str, Any]) -> ExternalObjectRecord:
        return ExternalObjectRecord(
            tenant_id=tenant_id,
            provider_id=self.metadata.provider_id,
            external_object_id=str(payload["external_object_id"]),
            object_type=str(payload.get("object_type", "post")),
            object_url=payload.get("object_url"),
            observed_at=payload.get("observed_at") or utc_now(),
            evidence_ref=payload.get("evidence_ref"),
        )

    def verify_action(self, action: ProviderActionRecord, provider_snapshot: Mapping[str, Any] | None) -> ProviderVerificationRecord:
        verified_at = utc_now()
        if not provider_snapshot:
            return ProviderVerificationRecord(
                tenant_id=action.tenant_id,
                provider_id=action.provider_id,
                provider_action_id=action.provider_action_id,
                verification_status=ProviderVerificationStatus.UNVERIFIED,
                verification_source="provider_api_read",
                confidence=0.0,
                verified_at=verified_at,
                provider_request_id=action.provider_request_id,
                external_object_id=action.external_object_id,
                evidence_ref=action.evidence_ref,
                contradiction_reason="missing_provider_snapshot",
            )

        snapshot_object_id = provider_snapshot.get("external_object_id") or provider_snapshot.get("id")
        snapshot_action_type = provider_snapshot.get("action_type") or provider_snapshot.get("object_type")
        object_matches = not action.external_object_id or str(snapshot_object_id) == action.external_object_id
        action_supported = action.action_type in self.metadata.supported_events or str(snapshot_action_type) == action.action_type
        if object_matches and action_supported:
            return ProviderVerificationRecord(
                tenant_id=action.tenant_id,
                provider_id=action.provider_id,
                provider_action_id=action.provider_action_id,
                verification_status=ProviderVerificationStatus.PROVIDER_CONFIRMED,
                verification_source="provider_api_read",
                confidence=0.95,
                verified_at=verified_at,
                provider_request_id=action.provider_request_id,
                external_object_id=action.external_object_id or str(snapshot_object_id),
                evidence_ref=provider_snapshot.get("evidence_ref") or action.evidence_ref,
            )

        return ProviderVerificationRecord(
            tenant_id=action.tenant_id,
            provider_id=action.provider_id,
            provider_action_id=action.provider_action_id,
            verification_status=ProviderVerificationStatus.CONTRADICTED,
            verification_source="provider_api_read",
            confidence=0.9,
            verified_at=verified_at,
            provider_request_id=action.provider_request_id,
            external_object_id=action.external_object_id,
            evidence_ref=provider_snapshot.get("evidence_ref") or action.evidence_ref,
            contradiction_reason="provider_snapshot_mismatch",
        )

    def consume_webhook(self, tenant_id: str, body: bytes, headers: Mapping[str, str], secret: str | None = None) -> list[ProviderVerificationRecord]:
        if secret:
            signature = headers.get("x-aether-provider-signature") or headers.get("x-x-signature")
            expected = hmac.new(secret.encode("utf-8"), body, sha256).hexdigest()
            if not signature or not hmac.compare_digest(signature, expected):
                raise ValueError("invalid provider webhook signature")
        payload = json.loads(body.decode("utf-8"))
        action = self.normalize_action(tenant_id, payload)
        return [self.verify_action(action, payload.get("provider_snapshot") or payload)]

    def health_check(self) -> ProviderHealthRecord:
        return ProviderHealthRecord(provider_id=self.metadata.provider_id, status="available", checked_at=utc_now(), rate_limit_state="not_limited")


def compute_permission_findings(
    *,
    tenant_id: str,
    grants: Sequence[AuthorizationGrantRecord],
    actions: Sequence[ProviderActionRecord],
    approved_scope_baselines: Mapping[str, set[str]] | None = None,
) -> list[PermissionFinding]:
    findings: list[PermissionFinding] = []
    actions_by_grant = {action.authorization_id for action in actions if action.authorization_id}
    now = utc_now()
    approved_scope_baselines = approved_scope_baselines or {}

    for grant in grants:
        write_scopes = tuple(scope for scope in grant.scopes if "write" in scope or scope.endswith(".manage"))
        if write_scopes and grant.authorization_id not in actions_by_grant:
            findings.append(
                PermissionFinding(
                    tenant_id=tenant_id,
                    finding_type="write_scope_unused",
                    severity="medium",
                    reason_codes=("write_scope_without_observed_use",),
                    affected_entities=(grant.authorization_id, grant.external_account_id),
                    evidence_refs=tuple(ref for ref in (grant.evidence_ref,) if ref),
                    recommended_action="review_scope_with_human_owner",
                )
            )
        if grant.expires_at and grant.expires_at < now:
            findings.append(
                PermissionFinding(
                    tenant_id=tenant_id,
                    finding_type="expired_grant",
                    severity="high",
                    reason_codes=("grant_expired",),
                    affected_entities=(grant.authorization_id, grant.external_account_id),
                    evidence_refs=tuple(ref for ref in (grant.evidence_ref,) if ref),
                    recommended_action="route_grant_for_human_review",
                )
            )
        if grant.revoked_at and grant.authorization_id in actions_by_grant:
            findings.append(
                PermissionFinding(
                    tenant_id=tenant_id,
                    finding_type="revoked_grant_used",
                    severity="critical",
                    reason_codes=("observed_action_after_revocation",),
                    affected_entities=(grant.authorization_id, grant.external_account_id),
                    evidence_refs=tuple(ref for ref in (grant.evidence_ref,) if ref),
                    recommended_action="investigate_and_confirm_provider_state",
                )
            )
        baseline = approved_scope_baselines.get(grant.grantor_id or "")
        if baseline is not None:
            unexpected = tuple(sorted(set(grant.scopes) - baseline))
            if unexpected:
                findings.append(
                    PermissionFinding(
                        tenant_id=tenant_id,
                        finding_type="unexpected_new_scope",
                        severity="high",
                        reason_codes=tuple(f"unexpected_scope:{scope}" for scope in unexpected),
                        affected_entities=(grant.authorization_id, grant.external_account_id),
                        evidence_refs=tuple(ref for ref in (grant.evidence_ref,) if ref),
                        recommended_action="compare_against_approved_baseline",
                    )
                )
    return findings


def build_provider_graph_projection(
    account: ExternalAccountRecord,
    grant: AuthorizationGrantRecord | None = None,
    action: ProviderActionRecord | None = None,
    verification: ProviderVerificationRecord | None = None,
) -> list[dict[str, Any]]:
    """Build provider-neutral graph projection records without writing the graph."""

    records: list[dict[str, Any]] = [
        {
            "kind": "vertex",
            "type": "ExternalAccount",
            "id": f"external_account:{account.tenant_id}:{account.provider_id}:{account.external_account_id}",
            "tenantId": account.tenant_id,
            "provider": account.provider_id,
            "external_account_id": account.external_account_id,
            "evidence_ref": account.evidence_ref,
        }
    ]
    if grant:
        grant_id = f"authorization_grant:{grant.tenant_id}:{grant.authorization_id}"
        records.append(
            {
                "kind": "vertex",
                "type": "AuthorizationGrant",
                "id": grant_id,
                "tenantId": grant.tenant_id,
                "provider": grant.provider_id,
                "authorization_id": grant.authorization_id,
                "scope_hash": grant.scope_hash,
                "credential_ref": grant.credential_ref,
                "evidence_ref": grant.evidence_ref,
            }
        )
        records.append(
            {
                "kind": "edge",
                "type": "LINKED_TO_EXTERNAL_ACCOUNT",
                "id": f"edge:{grant_id}:account:{account.external_account_id}",
                "tenantId": grant.tenant_id,
                "from": grant_id,
                "to": records[0]["id"],
                "valid_from": grant.approved_at,
                "valid_to": grant.revoked_at or grant.expires_at,
                "is_current": grant.revoked_at is None,
            }
        )
    if action:
        action_id = f"provider_action:{action.tenant_id}:{action.provider_action_id}"
        records.append(
            {
                "kind": "vertex",
                "type": "ProviderAction",
                "id": action_id,
                "tenantId": action.tenant_id,
                "provider": action.provider_id,
                "action_type": action.action_type,
                "provider_request_id": action.provider_request_id,
                "external_object_id": action.external_object_id,
                "evidence_ref": action.evidence_ref,
            }
        )
    if verification and action:
        records.append(
            {
                "kind": "vertex",
                "type": "ProviderVerification",
                "id": f"provider_verification:{verification.tenant_id}:{verification.provider_action_id}:{verification.verification_status.value}",
                "tenantId": verification.tenant_id,
                "provider": verification.provider_id,
                "verification_status": verification.verification_status.value,
                "verification_source": verification.verification_source,
                "confidence": verification.confidence,
                "evidence_ref": verification.evidence_ref,
                "contradiction_reason": verification.contradiction_reason,
            }
        )
    return records


provider_registry = ProviderRegistry()
provider_registry.register(XReferenceAdapter())
