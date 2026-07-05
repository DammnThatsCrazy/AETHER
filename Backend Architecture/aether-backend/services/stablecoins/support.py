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

class StablecoinSupportService:
    def __init__(self, repo: StablecoinSupportAssertionRepository | None = None) -> None:
        self.repo = repo or StablecoinSupportAssertionRepository()

    async def assert_support(self, evidence: SupportEvidence) -> dict[str, Any]:
        if not evidence.tenant_id:
            raise ValueError("tenant_id is required for support assertions")
        if not evidence.evidence_reference:
            raise ValueError("support assertion requires evidence_reference")
        assertion_id = f"stablecoin_support:{evidence.tenant_id}:{evidence.subject_entity_id}:{evidence.deployment_id}:{evidence.capability.value}"
        existing = await self.repo.find_by_id(assertion_id)
        previous_state = SupportState(existing.get("support_state", SupportState.UNKNOWN.value)) if existing else SupportState.UNKNOWN
        if evidence.support_state not in _ALLOWED_SUPPORT_TRANSITIONS[previous_state] and evidence.support_state != previous_state:
            raise ValueError(f"invalid support transition {previous_state.value}->{evidence.support_state.value}")
        now = utc_now().isoformat()
        history = list(existing.get("state_history", [])) if existing else []
        history.append({"from": previous_state.value, "to": evidence.support_state.value, "at": now, "evidence_reference": evidence.evidence_reference})
        record = {
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
