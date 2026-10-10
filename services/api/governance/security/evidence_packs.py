"""Governance Evidence Packs.

Generates security-review evidence packs. Each pack summarizes a control area:
its control summary, relevant policies, audit-event summaries, verifier results
(where applicable), and known gaps — with a generated_at timestamp and integrity
hash. These are evidence for security review, NOT compliance certifications.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import timedelta
from typing import Any, Optional

from shared.common.common import utc_now
from shared.logger.logger import get_logger

from .access_control import ROLE_GRANTS, ROLE_SPECS
from .audit_ledger import audit_ledger
from .contracts import (
    EvidencePackType,
    GovernanceEvidencePack,
    now_iso,
    sanitize_metadata,
)
from .isolation_verifier import tenant_isolation_verifier
from .policy_engine import policy_engine, _SENSITIVE_KEYS
from .repositories import EvidencePackRepository, SecurityAuditEventRepository

logger = get_logger("aether.security.evidence_packs")

# Per-pack-type control summary + known gaps. Gaps are stated honestly — these
# are NOT certified controls.
PACK_DEFINITIONS: dict[EvidencePackType, dict[str, Any]] = {
    "access_control": {
        "controls": [
            "Role-to-permission mapping (AccessControlService.ROLE_GRANTS)",
            "Domain/action/scope evaluation on access checks",
            "Audit events emitted for denials and sensitive allows",
        ],
        "gaps": [
            "Not externally certified (no SOC 2 / ISO attestation claimed)",
            "Role assignment provisioning lives in existing auth, not yet unified here",
        ],
    },
    "tenant_isolation": {
        "controls": [
            "TenantIsolationVerifier scans resource stores for tenant_id presence",
            "Aggregate-only Kyber views (no raw cross-tenant passthrough)",
            "Cross-tenant access blocked by PolicyEngine",
        ],
        "gaps": ["Verifier samples stores; not a continuous real-time guarantee"],
    },
    "audit_logging": {
        "controls": [
            "Tamper-evident SecurityAuditEvent ledger with chained integrity hashes",
            "Audit events for access checks, policy decisions, exports, break-glass",
            "Secret sanitization on all audit metadata",
        ],
        "gaps": ["Ledger chaining is best-effort in the JSONB store; no external WORM yet"],
    },
    "data_retention": {
        "controls": [
            "Per-resource retention policies with delete-behavior controls",
            "Audit logs never hard-deleted; billing records preserved",
            "Data requests processed as structured, audited records",
        ],
        "gaps": ["Automated enforcement/sweeps not yet scheduled; policies are declarative"],
    },
    "integration_security": {
        "controls": [
            "HMAC webhook signing + secret rotation (secrets never returned)",
            "Destination safety validation (blocks private/loopback/metadata)",
            "Idempotency + retry limits + repeated-failure detection",
        ],
        "gaps": ["Per-tenant allowlists are optional and not enforced by default"],
    },
    "ai_recommendation_governance": {
        "controls": [
            "Recommendation persistence + decision approval gated by PolicyEngine",
            "Elevated/critical dispatch requires approval_id (human-in-the-loop)",
            "Dispatch blocked unless decision is approved",
        ],
        "gaps": ["Model-level explainability evidence sourced from existing OODA layer"],
    },
    "operator_access": {
        "controls": [
            "Olympus operator access is scoped (assigned/aggregate) by role",
            "Break-glass access is time-boxed, approval-gated, and fully audited",
            "Every access used under a break-glass grant is audited",
        ],
        "gaps": ["Operator identity federation is out of scope for this control plane"],
    },
}


def _pack_integrity_hash(pack: GovernanceEvidencePack, body: dict[str, Any]) -> str:
    payload = json.dumps(
        {"id": pack.evidence_pack_id, "type": pack.pack_type, "body": body},
        sort_keys=True, default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class EvidencePackService:
    def __init__(
        self,
        repo: Optional[EvidencePackRepository] = None,
        audit_repo: Optional[SecurityAuditEventRepository] = None,
    ) -> None:
        self._repo = repo or EvidencePackRepository()
        self._audit_repo = audit_repo or SecurityAuditEventRepository()

    async def _build_body(
        self, pack_type: EvidencePackType, tenant_id: Optional[str],
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"control_summary": PACK_DEFINITIONS[pack_type]["controls"]}

        # Audit-event summary (counts by event_type).
        events = (
            await self._audit_repo.list_for_tenant(tenant_id, limit=5000)
            if tenant_id else await self._audit_repo.list_all(limit=5000)
        )
        body["audit_event_summary"] = dict(Counter(e.get("event_type", "?") for e in events))
        body["audit_events_total"] = len(events)

        if pack_type == "access_control":
            body["relevant_policies"] = ["access_control.evaluate"]
            body["roles"] = {role: len(ROLE_GRANTS.get(role, [])) for role in ROLE_SPECS}
        elif pack_type == "tenant_isolation":
            body["relevant_policies"] = ["cross_tenant.access", "kyber.operator_access"]
            body["verifier_result"] = await tenant_isolation_verifier.latest() or await tenant_isolation_verifier.run()
        elif pack_type == "audit_logging":
            body["relevant_policies"] = sorted(_SENSITIVE_KEYS)
            body["chain_verification"] = await audit_ledger.verify_chain(tenant_id)
        elif pack_type == "ai_recommendation_governance":
            body["relevant_policies"] = ["recommendation.persist", "decision.approve", "action.dispatch", "action.elevated_dispatch"]
            body["recent_policy_decisions"] = len(await policy_engine.list_decisions(tenant_id, limit=500))
        elif pack_type == "integration_security":
            body["relevant_policies"] = ["webhook.dispatch_safety", "integration.configure"]
        elif pack_type == "operator_access":
            body["relevant_policies"] = ["kyber.operator_access"]
        elif pack_type == "data_retention":
            body["relevant_policies"] = ["data.deletion_request"]

        return sanitize_metadata(body)

    async def generate(
        self, *, pack_type: EvidencePackType, requested_by: str,
        tenant_id: Optional[str] = None, valid_days: int = 30,
    ) -> GovernanceEvidencePack:
        definition = PACK_DEFINITIONS[pack_type]
        pack = GovernanceEvidencePack(
            tenant_id=tenant_id, pack_type=pack_type, status='queued',
            included_controls=list(definition["controls"]),
            known_gaps=list(definition["gaps"]), requested_by=requested_by,
        )
        try:
            body = await self._build_body(pack_type, tenant_id)
            pack.status = 'generated'
            pack.generated_at = now_iso()
            pack.expires_at = (utc_now() + timedelta(days=valid_days)).isoformat()
            pack.integrity_hash = _pack_integrity_hash(pack, body)
            record = pack.model_dump()
            record["body"] = body
            record["disclaimer"] = (
                "Security-review evidence only. Does NOT constitute or claim any "
                "compliance certification (e.g. SOC 2, ISO 27001, FedRAMP)."
            )
        except Exception as exc:  # pragma: no cover - defensive
            pack.status = 'failed'
            record = pack.model_dump()
            record["error"] = type(exc).__name__

        await self._repo.insert(pack.evidence_pack_id, record)
        await audit_ledger.record(
            actor_id=requested_by, actor_type='olympus_operator',
            event_type="evidence_pack.generated", resource_type="governance_evidence_pack",
            action="export", outcome='allowed' if pack.status == 'generated' else 'failed',
            tenant_id=tenant_id, resource_id=pack.evidence_pack_id,
            metadata={"pack_type": pack_type, "status": pack.status},
        )
        return pack

    async def list_packs(self, tenant_id: Optional[str] = None, limit: int = 100) -> list[dict]:
        if tenant_id is None:
            return await self._repo.list_all(limit=limit)
        return await self._repo.list_for_tenant(tenant_id, limit=limit)


evidence_pack_service = EvidencePackService()
