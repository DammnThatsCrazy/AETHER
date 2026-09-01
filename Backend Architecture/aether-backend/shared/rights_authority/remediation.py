"""Revocation impact execution with honest, durable receipts.

The authority owns the plan; storage/search/vector/model adapters own the
actual quarantine, deletion, and recomputation operations. This module
coordinates that boundary. It never marks an impact complete without an
adapter callback returning successfully for every affected node.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Optional

from shared.rights_authority.contracts import (
    ArtifactRef,
    RightsRemediationReceipt,
    RightsRemediationStep,
)
from shared.rights_authority.service import RightsAuthority, rights_authority

RemediationExecutor = Callable[[ArtifactRef, str], Awaitable[Optional[dict[str, Any]]]]


async def execute_impact(
    impact_graph_id: str,
    *,
    authority: RightsAuthority = rights_authority,
    executor: Optional[RemediationExecutor] = None,
) -> dict[str, Any]:
    """Attempt every impact step and return a receipt-backed status.

    With no executor, steps are recorded as ``blocked``. That is the safe
    default while a concrete adapter is unavailable and makes the missing
    provider visible to operators instead of fabricating completion.
    """
    impact = await authority.repository.get_impact(impact_graph_id)
    if impact is None:
        raise ValueError(f"impact graph unavailable: {impact_graph_id}")

    receipt_refs: list[str] = []
    outcomes: list[str] = []
    for node in impact.get("nodes") or []:
        artifact = ArtifactRef(**node["artifact_ref"])
        step = RightsRemediationStep(
            impact_graph_id=impact_graph_id,
            artifact_ref=artifact,
            action=node.get("remediation_action") or "quarantine_and_recompute",
            status="running" if executor else "blocked",
        )
        await authority.record_remediation_step(step)

        if executor is None:
            outcome = "blocked"
            detail = "remediation adapter is not registered"
        else:
            try:
                result = await executor(artifact, step.action)
                outcome = "completed"
                detail = str((result or {}).get("detail", "")) or None
            except Exception as exc:  # noqa: BLE001 — receipt the failure
                outcome = "failed"
                detail = type(exc).__name__

        receipt = RightsRemediationReceipt(
            impact_graph_id=impact_graph_id,
            step_id=step.step_id,
            artifact_ref=artifact,
            action=step.action,
            outcome=outcome,
            detail=detail,
        )
        await authority.record_remediation_receipt(receipt)
        receipt_refs.append(receipt.receipt_id)
        outcomes.append(outcome)
        await authority.record_remediation_step(step.model_copy(update={
            "step_id": f"{step.step_id}:v2",
            "status": outcome,
            "receipt_refs": [receipt.receipt_id],
        }))

    final_status = "completed" if outcomes and all(x == "completed" for x in outcomes) else "blocked"
    if not outcomes:
        final_status = "completed"
    updated = await authority.update_impact_status(
        impact_graph_id,
        final_status,
        receipt_refs=receipt_refs,
    )
    return {
        "impact_graph_id": impact_graph_id,
        "status": updated.status,
        "receipt_refs": receipt_refs,
        "outcomes": outcomes,
    }


__all__ = ["RemediationExecutor", "execute_impact"]
