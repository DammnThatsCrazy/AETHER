"""Request-time authorization for the governed Experience 360 frame API.

The evaluator adapts the existing central AccessControlService to the frame
runtime. Every slot is checked against every governed authority domain named by
its catalog contract; an unclassified authority fails closed. This is access
authorization, not a substitute for consent, source authority, or field-level
redaction decisions made by canonical domain services.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import Request

from governance.security.access_control import access_control
from governance.security.request_context import tenant_actor
from shared.intelligence_projections.contracts import (
    Experience360FrameRequest,
    Experience360PolicyDisposition,
    Experience360PolicyEvaluation,
)
from shared.intelligence_projections.generated_registry import (
    PRODUCT_360_SURFACE_DEFINITIONS,
)


# Authority references are intentionally mapped in code rather than guessed
# from caller-controlled purpose strings. A new catalog reference must receive
# an explicit authorization domain before its content can be read.
AUTHORITY_DOMAIN_BY_REF: dict[str, str] = {
    "actions": "actions",
    "agent_access": "governance",
    "agent_entities": "profile",
    "agent_entity": "profile",
    "agent_executions": "actions",
    "ai_execution_facts": "actions",
    "attribution_runs": "outcomes",
    "attribution_credits": "outcomes",
    "behavioral_signals": "data_quality",
    "campaign_facts": "outcomes",
    "campaign_touchpoints": "outcomes",
    "canonical_conversions": "outcomes",
    "cohort_membership": "profile",
    "cluster_definitions": "profile",
    "cluster_membership": "profile",
    "commerce": "billing",
    "commerce_product_offer_graph": "billing",
    "communication_facts": "integrations",
    "context_capsules": "graph",
    "computation": "graph",
    "consent_policy_decisions": "governance",
    "currency_value_normalization": "billing",
    "economic_facts": "billing",
    "entity_graph": "graph",
    "entity_registry": "profile",
    "entities": "profile",
    "episode_facts": "graph",
    "events": "graph",
    "evidence": "data_exchange",
    "execution_facts": "actions",
    "flow_trace_paths": "actions",
    "flow_traces": "actions",
    "fraud_synthesis": "security",
    "geo_observations": "profile",
    "gold_temporal_heatmap": "graph",
    "graph": "graph",
    "graph_motifs": "graph",
    "identity": "profile",
    "influence_propagation": "graph",
    "ingestion_health": "data_quality",
    "journeys": "graph",
    "locations": "profile",
    "measurement_contract": "outcomes",
    "model_governance": "governance",
    "observations": "graph",
    "outcome_facts": "outcomes",
    "payments": "billing",
    "population_definitions": "profile",
    "provider_connections": "integrations",
    "relationship_facts": "graph",
    "relationship_fidelity": "graph",
    "relationship_predicate_registry": "graph",
    "resources": "actions",
    "risk_assessments": "security",
    "risk_outputs": "security",
    "risk_signals": "security",
    "semantic_memory_graph": "graph",
    "semantic_memory_records": "graph",
    "silver_semantic_observations": "graph",
    "social_observations": "graph",
    "source_coverage": "data_exchange",
    "source_facts": "data_exchange",
    "source_provenance": "data_exchange",
    "source_schema": "data_exchange",
    "support_case_events": "customer_success",
    "support_cases": "customer_success",
    "temporal": "graph",
    "temporal_kernel": "graph",
    "targeting_leakage_findings": "security",
    "tools": "actions",
    "transfers": "billing",
    "touchpoints": "outcomes",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RequestAccessPolicyEvaluator:
    """Evaluate frame and slot reads using the authenticated request actor."""

    def __init__(self, request: Request) -> None:
        self._request = request

    async def evaluate(
        self, frame_request: Experience360FrameRequest
    ) -> Experience360PolicyEvaluation:
        actor = tenant_actor(self._request)
        if actor.tenant_id != frame_request.tenantId:
            raise ValueError("authenticated actor tenant does not match frame tenant")

        surface = PRODUCT_360_SURFACE_DEFINITIONS.get(frame_request.surfaceId)
        if not isinstance(surface, dict):
            raise ValueError("unknown product 360 surface")

        evaluated_at = _utc_now_iso()
        slot_definitions = surface.get("domainSlots", [])
        if not isinstance(slot_definitions, list):
            raise ValueError("invalid product 360 surface contract")

        requested = (
            {slot.get("id") for slot in slot_definitions if isinstance(slot, dict)}
            if frame_request.requestedSlotIds is None
            else set(frame_request.requestedSlotIds)
        )
        domains_by_slot: dict[str, set[str]] = {}
        unresolved_by_slot: set[str] = set()
        for slot in slot_definitions:
            if not isinstance(slot, dict) or not isinstance(slot.get("id"), str):
                raise ValueError("invalid product 360 slot contract")
            slot_id = slot["id"]
            if slot_id not in requested:
                continue
            refs = slot.get("canonicalAuthorityRefs")
            if not isinstance(refs, (list, tuple)) or not refs:
                unresolved_by_slot.add(slot_id)
                continue
            domains: set[str] = set()
            for ref in refs:
                if not isinstance(ref, str) or ref not in AUTHORITY_DOMAIN_BY_REF:
                    unresolved_by_slot.add(slot_id)
                    continue
                domains.add(AUTHORITY_DOMAIN_BY_REF[ref])
            if domains:
                domains_by_slot[slot_id] = domains

        unique_domains = sorted(
            {domain for domains in domains_by_slot.values() for domain in domains}
        )
        decisions: dict[str, Any] = {}
        for domain in unique_domains:
            decisions[domain] = await access_control.evaluate(
                actor_id=actor.actor_id,
                actor_type=actor.actor_type,
                roles=actor.roles,
                domain=domain,
                action="read",
                actor_tenant=actor.tenant_id,
                target_tenant=frame_request.tenantId,
                resource_type="experience360",
                resource_id=f"{frame_request.surfaceId}:{domain}",
                ip_address=actor.ip_address,
                user_agent=actor.user_agent,
            )

        slot_dispositions: dict[str, Experience360PolicyDisposition] = {}
        for slot_id in sorted(requested):
            if slot_id in unresolved_by_slot or slot_id not in domains_by_slot:
                slot_dispositions[slot_id] = Experience360PolicyDisposition(
                    state="unknown",
                    policyIds=["access_control.evaluate"],
                    reasonCodes=["authority_domain_unclassified"],
                    evaluatedAt=evaluated_at,
                )
                continue
            slot_decisions = [decisions[domain] for domain in sorted(domains_by_slot[slot_id])]
            allowed = all(decision.allowed for decision in slot_decisions)
            slot_dispositions[slot_id] = Experience360PolicyDisposition(
                state="allowed" if allowed else "denied",
                policyIds=sorted({decision.policy_key for decision in slot_decisions}),
                reasonCodes=["access_granted" if allowed else "access_denied"],
                evaluatedAt=evaluated_at,
            )

        # The route has already required tenant read permission. Slot decisions
        # further restrict sensitive domains; they never elevate the frame.
        return Experience360PolicyEvaluation(
            surfaceId=frame_request.surfaceId,
            tenantId=frame_request.tenantId,
            evaluatedAt=evaluated_at,
            frameDisposition=Experience360PolicyDisposition(
                state="allowed",
                policyIds=["authenticated_tenant_read"],
                reasonCodes=["tenant_read_permission_required"],
                evaluatedAt=evaluated_at,
            ),
            slotDispositions=slot_dispositions,
        )


__all__ = ["AUTHORITY_DOMAIN_BY_REF", "RequestAccessPolicyEvaluator"]
