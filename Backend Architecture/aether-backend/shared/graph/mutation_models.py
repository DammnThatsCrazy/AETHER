"""Hand-authored graph-mutation ledger models.

TS twins: the ``MutationRecord``, ``GraphDecisionRecord``, and ``ChangeSet``
interfaces in ``packages/shared/graph-mutation.ts`` (emitted by
``scripts/generate_platform_contracts.py``; the decision twin carries the
``Graph`` prefix only because the barrel already exports another
``DecisionRecord``). The taxonomy tuples live in
``shared.graph.generated_mutation_taxonomy`` — regenerate, never edit.

Bitemporal invariant: :class:`MutationRecord` uses exactly the field names in
``shared.graph.edge_properties.BITEMPORAL_EDGE_PROPERTIES``
(``valid_from`` / ``valid_to`` / ``recorded_at`` / ``superseded_at``), enforced
by ``tests/contracts/test_graph_mutation_parity.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class MutationRecord(BaseModel):
    """One append-only graph mutation (the graph plane's ledger entry)."""

    model_config = ConfigDict(extra="forbid")

    mutation_id: str
    tenant_id: str
    aggregate_type: Literal["node", "edge", "cluster", "score"]
    aggregate_id: str
    operation: str
    actor_kind: Optional[str] = None
    actor_id: Optional[str] = None
    subject_kind: Optional[str] = None
    subject_id: Optional[str] = None
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    recorded_at: datetime
    superseded_at: Optional[datetime] = None
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None
    source_event_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    reason_code: Optional[str] = None
    causality_class: Optional[str] = None
    confidence: Optional[float] = None
    evidence_refs: Optional[list[str]] = None
    model_refs: Optional[list[str]] = None
    policy_refs: Optional[list[str]] = None
    consent_refs: Optional[list[str]] = None
    before_version_id: Optional[str] = None
    after_version_id: Optional[str] = None
    change_set_id: Optional[str] = None
    schema_version: Optional[str] = None


class DecisionRecord(BaseModel):
    """Point-in-time decision snapshot pinned to fact/model/policy versions."""

    model_config = ConfigDict(extra="forbid")

    decision_id: str
    tenant_id: str
    decision_type: str
    subject_refs: Optional[list[str]] = None
    input_fact_versions: Optional[dict[str, str]] = None
    graph_watermark: Optional[str] = None
    model_versions: Optional[dict[str, str]] = None
    policy_versions: Optional[dict[str, str]] = None
    decision: Optional[str] = None
    confidence: Optional[float] = None
    human_override: Optional[bool] = None
    action_observed: Optional[bool] = None
    outcome_refs: Optional[list[str]] = None
    valid_at: Optional[datetime] = None
    recorded_at: Optional[datetime] = None


class ChangeSet(BaseModel):
    """Digest of graph deltas between a baseline ref and a target ref."""

    model_config = ConfigDict(extra="forbid")

    change_set_id: str
    tenant_id: str
    scope_type: Optional[str] = None
    scope_id: Optional[str] = None
    baseline_ref: Optional[str] = None
    target_ref: Optional[str] = None
    added_node_count: Optional[int] = None
    removed_node_count: Optional[int] = None
    changed_edge_count: Optional[int] = None
    digest: Optional[str] = None


__all__ = ["MutationRecord", "DecisionRecord", "ChangeSet"]
