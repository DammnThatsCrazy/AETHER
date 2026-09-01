"""Durable jobs-plane handlers for rights remediation and audit delivery."""

from __future__ import annotations

from services.jobs.handlers import HANDLER_REGISTRY, JobOutcome, register_handler
from shared.rights_authority.remediation import execute_impact
from shared.rights_authority.audit_outbox import flush_audit_outbox

JOB_TYPE = "rights.remediation"
AUDIT_OUTBOX_JOB_TYPE = "rights.audit_outbox"


async def process_rights_remediation(payload: dict, ctx) -> JobOutcome:
    impact_graph_id = payload.get("impact_graph_id")
    if not impact_graph_id:
        return JobOutcome(status="failed", result={}, error="impact_graph_id is required")
    result = await execute_impact(impact_graph_id)
    status = "succeeded" if result.get("status") == "completed" else "failed"
    return JobOutcome(
        status=status,
        result=result,
        error=None if status == "succeeded" else "remediation adapter unavailable or failed",
    )


def register_rights_remediation_handler() -> None:
    if JOB_TYPE not in HANDLER_REGISTRY:
        register_handler(JOB_TYPE)(process_rights_remediation)


async def process_rights_audit_outbox(payload: dict, ctx) -> JobOutcome:
    result = await flush_audit_outbox(
        tenant_id=payload.get("tenant_id"),
        limit=int(payload.get("limit", 100)),
    )
    status = "failed" if result["failed"] and not result["delivered"] else "succeeded"
    return JobOutcome(
        status=status,
        result=result,
        error="one or more audit projections failed" if result["failed"] else None,
    )


def register_rights_audit_outbox_handler() -> None:
    if AUDIT_OUTBOX_JOB_TYPE not in HANDLER_REGISTRY:
        register_handler(AUDIT_OUTBOX_JOB_TYPE)(process_rights_audit_outbox)


__all__ = [
    "JOB_TYPE", "AUDIT_OUTBOX_JOB_TYPE", "process_rights_remediation",
    "process_rights_audit_outbox", "register_rights_remediation_handler",
    "register_rights_audit_outbox_handler",
]
