"""Stablecoin support assertions — which entity supports which capability
on which deployment, with evidence. State changes append new assertion rows
(corrections are new facts, never mutations)."""

from __future__ import annotations

from typing import Any, Optional

from repositories.stablecoin_repos import SupportAssertionRepo
from services.stablecoin.foundation import (
    deterministic_id,
    deterministic_idempotency_key,
    make_event,
    utc_now_iso,
)
from services.stablecoin.models import StablecoinSupportRequest

_REVOKED_STATES = {"degraded", "suspended", "retired"}


class SupportService:
    def __init__(self, assertion_repo: Optional[SupportAssertionRepo] = None) -> None:
        self.assertions = assertion_repo or SupportAssertionRepo()

    async def assert_support(
        self, tenant_id: str, request: StablecoinSupportRequest,
    ) -> dict[str, Any]:
        basis = (
            f"{request.subject_entity_ref.kind}:{request.subject_entity_ref.id}"
            f"|{request.deployment_id}|{request.capability}|{request.support_status}"
            f"|{request.environment}"
        )
        record = {
            "tenant_id": tenant_id,
            "assertion_id": deterministic_id("scsup_", basis),
            "subject_entity_ref": request.subject_entity_ref.model_dump(),
            "deployment_id": request.deployment_id,
            "capability": request.capability,
            "support_status": request.support_status,
            "environment": request.environment,
            "evidence_type": request.evidence_type,
            "evidence_reference": request.evidence_reference,
            "first_observed_at": request.first_observed_at or utc_now_iso(),
            "last_observed_at": request.last_observed_at or utc_now_iso(),
            "successful_observation_count": request.successful_observation_count,
            "failed_observation_count": request.failed_observation_count,
            "confidence": request.confidence,
            "expires_at": request.expires_at,
            "idempotency_key": deterministic_idempotency_key(basis),
            "evidence": request.evidence.model_dump() if request.evidence else None,
            "execution_by_aether": False,
        }
        inserted = await self.assertions.insert(record)

        emitted: list[dict] = []
        if inserted:
            event_name = (
                "stablecoin_support_revoked"
                if request.support_status in _REVOKED_STATES
                else "stablecoin_support_asserted"
            )
            emitted.append(make_event(event_name, tenant_id, {
                "assertion_id": record["assertion_id"],
                "subject_entity": f"{request.subject_entity_ref.kind}:{request.subject_entity_ref.id}",
                "deployment_id": request.deployment_id,
                "capability": request.capability,
                "support_status": request.support_status,
                "environment": request.environment,
            }))
        return {
            "inserted": inserted,
            "assertion_id": record["assertion_id"],
            "emitted_events": emitted,
        }
