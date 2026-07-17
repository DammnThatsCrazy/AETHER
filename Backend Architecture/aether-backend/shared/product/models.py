"""Hand-authored interaction payload model.

TS twin: the ``InteractionPayload`` interface in
``packages/shared/interaction-contract.ts`` (emitted by
``scripts/generate_platform_contracts.py``). The vocabulary tuples live in
``shared.product.generated_vocabulary`` — regenerate, never edit. Field-level
parity is enforced by ``tests/contracts/test_interaction_contract_parity.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class InteractionPayload(BaseModel):
    """One canonical product interaction.

    ``interaction_type`` is either a value from
    ``shared.product.generated_vocabulary.INTERACTION_TYPES`` or a
    ``<namespace>.<name>`` custom type under a registered namespace
    (unregistered custom types stay in Bronze, never stable Gold).
    """

    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    event_id: str
    occurred_at: datetime
    actor_kind: Optional[str] = None
    canonical_entity_id: Optional[str] = None
    anonymous_id: Optional[str] = None
    user_id: Optional[str] = None
    organization_id: Optional[str] = None
    workspace_id: Optional[str] = None
    agent_id: Optional[str] = None
    wallet_id: Optional[str] = None
    session_id: Optional[str] = None
    device_id: Optional[str] = None
    product_id: Optional[str] = None
    product_area_id: Optional[str] = None
    feature_id: Optional[str] = None
    feature_version_id: Optional[str] = None
    surface_id: Optional[str] = None
    control_id: Optional[str] = None
    interaction_type: Optional[str] = None
    action_type: Optional[str] = None
    result_state: Optional[str] = None
    status_detail: Optional[str] = None
    journey_id: Optional[str] = None
    journey_step_id: Optional[str] = None
    campaign_id: Optional[str] = None
    experiment_id: Optional[str] = None
    variant_id: Optional[str] = None
    channel: Optional[str] = None
    platform: Optional[str] = None
    application_id: Optional[str] = None
    application_version: Optional[str] = None
    sdk_name: Optional[str] = None
    sdk_version: Optional[str] = None
    chain_id: Optional[str] = None
    contract_address: Optional[str] = None
    transaction_hash: Optional[str] = None
    payment_rail: Optional[str] = None
    payment_provider: Optional[str] = None
    elapsed_ms: Optional[int] = None
    visible_ms: Optional[int] = None
    active_ms: Optional[int] = None
    engaged_ms: Optional[int] = None
    idle_ms: Optional[int] = None
    network_wait_ms: Optional[int] = None
    external_wait_ms: Optional[int] = None
    provider_wait_ms: Optional[int] = None
    execution_wait_ms: Optional[int] = None
    scroll_pct: Optional[float] = None
    viewable_pct: Optional[float] = None
    completion_pct: Optional[float] = None
    attempt_number: Optional[int] = None
    friction_type: Optional[str] = None
    error_code: Optional[str] = None
    failure_category: Optional[str] = None
    evidence_basis: Optional[str] = None
    confidence: Optional[float] = None
    consent_state: Optional[str] = None
    mapping_version: Optional[str] = None
    mapping_source: Optional[str] = None
    mapping_confidence: Optional[float] = None
    source_event_id: Optional[str] = None
    correlation_id: Optional[str] = None


__all__ = ["InteractionPayload"]
