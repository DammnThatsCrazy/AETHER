"""Normalizes x402 provider-specific payloads to canonical observation records."""
from __future__ import annotations

from datetime import datetime, timezone

from services.protocol_observability.x402_models import (
    X402InteractionObservedRecord,
    X402ChallengeObservedRecord,
    X402SettlementObservedRecord,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_x402_interaction(raw: dict, tenant_id: str) -> X402InteractionObservedRecord:
    if raw.get("execution_by_aether") is True:
        raise ValueError("execution_by_aether must be False")
    return X402InteractionObservedRecord(
        tenant_id=tenant_id,
        agent_id=raw.get("agent_id"),
        resource_url=raw.get("resource_url", ""),
        provider=raw.get("provider", "unknown"),
        observed_at=raw.get("observed_at") or _utc_now(),
    )


def normalize_x402_settlement(raw: dict, tenant_id: str) -> X402SettlementObservedRecord:
    if raw.get("execution_by_aether") is True:
        raise ValueError("execution_by_aether must be False")
    # settled_at comes from the observed_at field on X402SettlementRequest
    settled_at = raw.get("settled_at") or raw.get("observed_at") or _utc_now()
    return X402SettlementObservedRecord(
        tenant_id=tenant_id,
        interaction_id=raw.get("interaction_id"),
        tx_hash=raw.get("tx_hash"),
        settled_at=settled_at,
        settlement_by_external=True,
        execution_by_aether=False,
    )
