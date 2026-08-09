"""Evidence-backed stablecoin support state machine."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Mapping

from repositories.stablecoin_repos import StablecoinSupportAssertionRepository
from shared.common.common import utc_now

from .models import StablecoinCapability, SupportState

_ALLOWED_SUPPORT_TRANSITIONS: dict[SupportState, set[SupportState]] = {
    SupportState.UNKNOWN: {SupportState.ANNOUNCED, SupportState.REGISTERED, SupportState.UNSUPPORTED},
    SupportState.ANNOUNCED: {SupportState.REGISTERED, SupportState.CONFIGURED, SupportState.UNSUPPORTED, SupportState.RETIRED},
    SupportState.REGISTERED: {SupportState.CONFIGURED, SupportState.SANDBOX_TESTED, SupportState.SUSPENDED},
    SupportState.CONFIGURED: {SupportState.SANDBOX_TESTED, SupportState.PRODUCTION_TESTED, SupportState.DEGRADED, SupportState.SUSPENDED},
    SupportState.SANDBOX_TESTED: {SupportState.PRODUCTION_TESTED, SupportState.OBSERVED, SupportState.DEGRADED, SupportState.SUSPENDED},
    SupportState.PRODUCTION_TESTED: {SupportState.OBSERVED, SupportState.PRODUCTION_ACTIVE, SupportState.DEGRADED, SupportState.SUSPENDED},
    SupportState.OBSERVED: {SupportState.PRODUCTION_ACTIVE, SupportState.DEGRADED, SupportState.SUSPENDED, SupportState.DEPRECATED},
    SupportState.PRODUCTION_ACTIVE: {SupportState.DEGRADED, SupportState.SUSPENDED, SupportState.DEPRECATED, SupportState.RETIRED},
    SupportState.DEGRADED: {SupportState.PRODUCTION_ACTIVE, SupportState.SUSPENDED, SupportState.RETIRED},
    SupportState.SUSPENDED: {SupportState.CONFIGURED, SupportState.PRODUCTION_ACTIVE, SupportState.RETIRED, SupportState.UNSUPPORTED},
    SupportState.DEPRECATED: {SupportState.RETIRED},
    SupportState.RETIRED: set(),
    SupportState.UNSUPPORTED: {SupportState.ANNOUNCED, SupportState.REGISTERED},
}


@dataclass(frozen=True)
class SupportEvidence:
    tenant_id: str
    subject_entity_id: str
    deployment_id: str
    capability: StablecoinCapability
    support_state: SupportState
    evidence_type: str
    evidence_reference: str
    confidence: Decimal = Decimal("0.5")
    metadata: Mapping[str, Any] = field(default_factory=dict)


# Readiness rank per SupportState — the support ladder a tenant must climb
# before observation is allowed. Terminal/disabled states are unreachable.
_SUPPORT_READINESS_RANK: dict[SupportState, int] = {
    SupportState.UNKNOWN: 0,
    SupportState.ANNOUNCED: 1,
    SupportState.REGISTERED: 2,
    SupportState.CONFIGURED: 3,
    SupportState.SANDBOX_TESTED: 4,
    SupportState.PRODUCTION_TESTED: 5,
    SupportState.OBSERVED: 6,
    SupportState.PRODUCTION_ACTIVE: 7,
    SupportState.DEGRADED: 3,  # degraded is still usable — flagged, not blocked
    SupportState.SUSPENDED: -1,
    SupportState.DEPRECATED: -1,
    SupportState.RETIRED: -1,
    SupportState.UNSUPPORTED: -1,
}


class StablecoinReadinessError(Exception):
    """Observation is blocked until the tenant's support state is met.

    Carries the observed support state so operators can see exactly which
    state transition is outstanding — a missing assertion, a suspended
    deployment, or a state below the required ladder rung all resolve to a
    typed, fail-closed denial (never an empty healthy result).
    """

    def __init__(
        self,
        *,
        tenant_id: str,
        deployment_id: str,
        capability: StablecoinCapability,
        support_state: str,
        required_state: str,
        reason: str,
    ) -> None:
        self.tenant_id = tenant_id
        self.deployment_id = deployment_id
        self.capability = capability
        self.support_state = support_state
        self.required_state = required_state
        self.reason = reason
        super().__init__(
            f"stablecoin observation blocked: tenant={tenant_id} deployment={deployment_id} "
            f"capability={capability.value} support_state={support_state} required>={required_state} ({reason})"
        )


class StablecoinTenantReadinessGate:
    """Explicit tenant readiness gate for the observation path.

    Observation is blocked until a support assertion for the (tenant,
    deployment, capability) triple has climbed to at least ``required_state``
    (default CONFIGURED). Fails closed: a missing assertion, an unreadable
    store, or a suspended/retired deployment all deny observation — an error is
    NEVER reported as a healthy empty dataset.
    """

    def __init__(
        self,
        repo: StablecoinSupportAssertionRepository | None = None,
        required_state: SupportState = SupportState.CONFIGURED,
    ) -> None:
        self.repo = repo or StablecoinSupportAssertionRepository()
        self.required_state = required_state

    async def observation_ready(
        self,
        *,
        tenant_id: str,
        deployment_id: str,
        capability: StablecoinCapability = StablecoinCapability.OBSERVATION,
    ) -> dict[str, Any]:
        """Decision record — ``ready`` is False on ANY missing/unmet state."""
        assertion = await self._latest_assertion(tenant_id, deployment_id, capability)
        if not tenant_id or not deployment_id:
            return {
                "ready": False, "tenant_id": tenant_id, "deployment_id": deployment_id,
                "capability": capability.value, "support_state": "unresolved_identity",
                "required_state": self.required_state.value, "reason": "unresolved_identity",
            }
        if assertion is None:
            return {
                "ready": False, "tenant_id": tenant_id, "deployment_id": deployment_id,
                "capability": capability.value, "support_state": "missing_assertion",
                "required_state": self.required_state.value, "reason": "no_support_assertion",
            }
        raw_state = str(assertion.get("support_state") or SupportState.UNKNOWN.value)
        try:
            support_state = SupportState(raw_state)
        except ValueError:
            support_state = SupportState.UNKNOWN
        rank = _SUPPORT_READINESS_RANK.get(support_state, -1)
        required_rank = _SUPPORT_READINESS_RANK.get(self.required_state, 3)
        ready = rank >= required_rank
        return {
            "ready": ready, "tenant_id": tenant_id, "deployment_id": deployment_id,
            "capability": capability.value, "support_state": support_state.value,
            "required_state": self.required_state.value,
            "reason": "ready" if ready else "support_state_not_met",
        }

    async def require_observation(
        self,
        *,
        tenant_id: str,
        deployment_id: str,
        capability: StablecoinCapability = StablecoinCapability.OBSERVATION,
    ) -> dict[str, Any]:
        """Raise ``StablecoinReadinessError`` unless the tenant is ready."""
        decision = await self.observation_ready(tenant_id=tenant_id, deployment_id=deployment_id, capability=capability)
        if not decision["ready"]:
            raise StablecoinReadinessError(
                tenant_id=tenant_id,
                deployment_id=deployment_id,
                capability=capability,
                support_state=str(decision.get("support_state") or "unknown"),
                required_state=self.required_state.value,
                reason=str(decision.get("reason") or "not_ready"),
            )
        return decision

    async def _latest_assertion(
        self, tenant_id: str, deployment_id: str, capability: StablecoinCapability
    ) -> dict[str, Any] | None:
        rows = await self.repo.find_many(
            filters={"tenant_id": tenant_id, "deployment_id": deployment_id, "capability": capability.value},
            limit=1,
        )
        return rows[0] if rows else None


class StablecoinSupportService:
    def __init__(self, repo: StablecoinSupportAssertionRepository | None = None) -> None:
        self.repo = repo or StablecoinSupportAssertionRepository()

    async def assert_support(self, evidence: SupportEvidence) -> dict[str, Any]:
        if not evidence.tenant_id:
            raise ValueError("tenant_id is required for support assertions")
        if not evidence.evidence_reference:
            raise ValueError("support assertion requires evidence_reference")
        assertion_id = (
            f"stablecoin_support:{evidence.tenant_id}:{evidence.subject_entity_id}"
            f":{evidence.deployment_id}:{evidence.capability.value}"
        )
        existing = await self.repo.find_by_id(assertion_id)
        previous_state = (
            SupportState(existing.get("support_state", SupportState.UNKNOWN.value))
            if existing
            else SupportState.UNKNOWN
        )
        if (
            evidence.support_state not in _ALLOWED_SUPPORT_TRANSITIONS[previous_state]
            and evidence.support_state != previous_state
        ):
            raise ValueError(f"invalid support transition {previous_state.value}->{evidence.support_state.value}")
        now = utc_now().isoformat()
        history = list(existing.get("state_history", [])) if existing else []
        history.append({
            "from": previous_state.value,
            "to": evidence.support_state.value,
            "at": now,
            "evidence_reference": evidence.evidence_reference,
        })
        record: dict[str, Any] = {
            "assertion_id": assertion_id,
            "tenant_id": evidence.tenant_id,
            "subject_entity_id": evidence.subject_entity_id,
            "deployment_id": evidence.deployment_id,
            "capability": evidence.capability.value,
            "support_state": evidence.support_state.value,
            "evidence_type": evidence.evidence_type,
            "evidence_reference": evidence.evidence_reference,
            "evidence_timestamp": now,
            "confidence": str(evidence.confidence),
            "state_history": history,
            "metadata": dict(evidence.metadata),
        }
        return await self.repo.update(assertion_id, record) if existing else await self.repo.insert(assertion_id, record)
