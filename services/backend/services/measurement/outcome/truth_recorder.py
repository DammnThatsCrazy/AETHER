"""WS-D durable outcome-truth recorder (item 3 / gap row 26).

The canonical outcome read returns ``None`` (the outcome repository adapter
lands with the vertical slice); the durable truth STORE (:class:`OutcomeTruthStore`)
is the WS-D lineaged outcome surface. This recorder is the durable-write seam:
it converts a canonical :class:`Outcome` contract row (or a projected Silver
outcome row) into an :class:`OutcomeTruthRecord` that RETAINS the derivation
lineage the identity-style outcome read drops today — ``evidence_refs``,
``source_event_ids`` and ``model_version``/``policy_version`` — then persists it
idempotently.

Every write is gated on ``AETHER_OUTCOME_TRUTH_STORE_ENABLED`` (default OFF);
with the flag off the recorder is a no-op returning ``None``, so no behavior
changes anywhere. The durable row is additive: outcome_facts / measurement
Gold remain the system of record (ADR-010); this store is a lineage-rich
projection of them for the outcome360 + governance reads.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from shared.backend_interpretation.flags import outcome_truth_store_enabled
from shared.backend_interpretation.governance import assess_derived_write
from shared.backend_interpretation.observe import register_correlation_from_observation
from shared.backend_interpretation.primitives import OutcomeTruthRecord
from shared.backend_interpretation.stores import OutcomeTruthStore
from services.operational_intelligence.models import EntityRef

logger = logging.getLogger("aether.outcome.truth_recorder")

# Outcome event types -> outcome-truth state (finality ladder values; matches
# the measurement Outcome contract vocabulary, no second enum).
_STATE_BY_OUTCOME_TYPE: dict[str, str] = {
    "goal_achieved": "final",
    "goal_failed": "final",
    "recommendation_accepted": "reversible",
    "recommendation_rejected": "reversible",
    "retention_observed": "reversible",
    "churn_observed": "reversible",
    "feedback_submitted": "provisional",
    "outcome_observed": "provisional",
    "human_override_observed": "reversible",
}


async def persist_outcome_truth(
    record: OutcomeTruthRecord,
    store: Optional[OutcomeTruthStore] = None,
    *,
    register_correlation: bool = True,
) -> Optional[OutcomeTruthRecord]:
    """Persist one lineaged outcome-truth row (flag-gated no-op when OFF)."""
    if not outcome_truth_store_enabled():
        return None
    # WS-D item 8 derived-truth governance: rides AETHER_MUTATION_GATEWAY_MODE.
    # enforce blocks a lineage-incomplete derived write; shadow reports but
    # persists; off is byte-for-byte pass-through.
    decision = assess_derived_write(
        tenant_id=record.tenant_id,
        claim_type=record.claim_type,
        actor_kind="measurement",
        actor_id="outcome_truth_recorder",
        model_version=record.model_version,
        policy_refs=[record.policy_version] if record.policy_version else None,
        evidence_ids=[ref.id for ref in record.evidence_refs],
        source_event_id=record.source_event_ids[0] if record.source_event_ids else None,
        reason_code="outcome-truth:record",
    )
    if decision.mode != "off" and decision.violations:
        logger.warning(
            "outcome-truth derived-write governance (%s) violations: %s",
            decision.mode, list(decision.violations),
        )
    if decision.would_block:
        logger.warning(
            "outcome-truth derived-write BLOCKED by enforce governance for %s",
            record.outcome_id,
        )
        return None
    kv = store or OutcomeTruthStore()
    await kv.upsert(record)
    if register_correlation and record.tenant_id and record.source_event_ids:
        # Register the outcome's correlation family when present (item 6).
        family = None
        if record.source_event_ids:
            family = record.source_event_ids[0]
        if family:
            await register_correlation_from_observation(
                record.tenant_id,
                {
                    "correlation": {"correlation_id": family},
                    "event": {"id": family},
                    "source": {"type": "outcome_truth"},
                },
            )
    return record


async def record_from_silver_outcome(
    *,
    tenant_id: str,
    row: dict[str, Any],
    event_id: str,
    subject: Optional[EntityRef] = None,
    model_version: Optional[str] = None,
    policy_version: Optional[str] = None,
    store: Optional[OutcomeTruthStore] = None,
) -> Optional[OutcomeTruthRecord]:
    """Record a durable outcome-truth row from one Silver outcome fact row.

    The Silver outcome row (``services.silver.projectors.outcome_projector``) is
    the projection; this recorder captures the same fact WITH its evidence
    lineage (the originating ``event_id`` and the row's goal/recommendation ids)
    so derived claims retain what the identity-style audit drops.
    """
    if not outcome_truth_store_enabled():
        return None
    outcome_type = row.get("outcome_type") or "outcome_observed"
    evidence_refs = [
        {
            "id": event_id,
            "type": "event",
            "source": "silver_outcome_facts",
        }
    ]
    record = OutcomeTruthRecord(
        outcome_id=f"{tenant_id}:{event_id}:{outcome_type}",
        tenant_id=tenant_id,
        definition_ref=outcome_type,
        subject=subject,
        state=_STATE_BY_OUTCOME_TYPE.get(outcome_type, "provisional"),
        achieved_at=row.get("occurred_at"),
        value_amount=_safe_str(row.get("value_amount_exact") or row.get("value_amount")),
        value_currency=row.get("value_currency_exact") or row.get("value_currency"),
        value_state=(
            "present"
            if row.get("value_amount") is not None
            else ("zero" if row.get("value_amount") == 0 else "missing")
        ),
        claim_type="derived",
        model_version=model_version,
        policy_version=policy_version,
        evidence_refs=_to_evidence_list(evidence_refs),
        source_event_ids=[event_id] if event_id else [],
        observed_at=row.get("occurred_at"),
        goal_id=row.get("goal_id"),
        recommendation_id=row.get("recommendation_id"),
    )
    return await persist_outcome_truth(record, store=store)


def _safe_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _to_evidence_list(refs: list[dict[str, Any]]) -> list[Any]:
    from shared.backend_interpretation.primitives import evidence_ref

    return [
        evidence_ref(
            evidence_id=str(ref.get("id") or ""),
            evidence_type=str(ref.get("type") or "event"),
            source=str(ref.get("source") or ""),
        )
        for ref in refs
    ]


__all__ = ["persist_outcome_truth", "record_from_silver_outcome"]
