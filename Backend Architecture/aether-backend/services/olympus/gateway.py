"""Fail-closed gateway for promoting only generalized, released artifacts.

Tenant-derived data never reaches the Olympus graph through a normal graph
writer.  A promotion must carry transform evidence, approvals, an aggregate
threshold, and a release proof; the rights authority makes the durable signed
decision, then this gateway stamps the resulting generalized envelope onto
each graph mutation.  A persisted kill switch is checked before queueing and
before every mutation.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field

from repositories.repos import BaseRepository
from shared.graph.graph import Edge, Vertex
from shared.graph.mutation_gateway import MutationIntent, get_mutation_gateway
from shared.rights_authority.contracts import (
    ActorRef,
    ArtifactRef,
    AttachRightsEnvelope,
)
from shared.rights_authority.pep import evaluate_rights, rights_mode
from shared.rights_authority.service import rights_authority


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class OlympusPromotionRequest(BaseModel):
    model_config = {"extra": "forbid"}

    tenant_id: str
    input_envelope_refs: list[str] = Field(min_length=1)
    policy_set_ref: str
    source_grant_refs: list[str] = Field(default_factory=list)
    approval_refs: list[str] = Field(min_length=1)
    evidence: dict[str, Any] = Field(default_factory=dict)
    graph_mutations: list[dict[str, Any]] = Field(default_factory=list)
    requested_by: str


class _PromotionRepository:
    def __init__(self) -> None:
        self.promotions = BaseRepository("irrl_olympus_promotions")
        self.controls = BaseRepository("irrl_olympus_controls")

    async def append_promotion(self, row: dict[str, Any]) -> None:
        await self.promotions.insert(row["promotion_id"], row)

    async def get_promotion(self, promotion_id: str) -> Optional[dict[str, Any]]:
        return await self.promotions.find_by_id(promotion_id)

    async def append_promotion_revision(self, row: dict[str, Any]) -> None:
        await self.promotions.insert(
            f"{row['promotion_id']}:v{row['revision']}", row,
        )

    async def set_control(self, active: bool, actor_id: str, reason: str) -> None:
        await self.controls.insert(f"control:{uuid.uuid4().hex}", {
            "active": active,
            "actor_id": actor_id,
            "reason": reason,
            "created_at": _now(),
        })

    async def kill_switch_active(self) -> bool:
        rows = await self.controls.find_many(limit=1, sort_by="created_at", sort_order="desc")
        return bool(rows and rows[0].get("active"))


class OlympusGeneralizedGraphGateway:
    """Queue, authorize, and release generalized graph promotions."""

    def __init__(self, repository: Optional[_PromotionRepository] = None) -> None:
        self.repository = repository or _PromotionRepository()

    async def set_kill_switch(self, *, active: bool, actor_id: str, reason: str) -> None:
        if not reason.strip():
            raise ValueError("kill-switch changes require a reason")
        await self.repository.set_control(active, actor_id, reason)

    async def enqueue(self, request: OlympusPromotionRequest) -> dict[str, Any]:
        if await self.repository.kill_switch_active():
            raise RuntimeError("olympus_generalized_graph_kill_switch_active")
        if not request.tenant_id or not request.requested_by:
            raise ValueError("tenant_id and requested_by are required")
        promotion_id = f"oprom_{uuid.uuid4().hex}"
        row = {
            "promotion_id": promotion_id,
            "tenant_id": request.tenant_id,
            "status": "pending",
            "revision": 1,
            "request": request.model_dump(mode="json"),
            "created_at": _now(),
            "updated_at": _now(),
        }
        await self.repository.append_promotion(row)
        return {"promotion_id": promotion_id, "status": "pending"}

    async def process(self, promotion_id: str) -> dict[str, Any]:
        row = await self.repository.get_promotion(promotion_id)
        if row is None:
            raise ValueError(f"promotion not found: {promotion_id}")
        if row.get("status") == "released":
            return row
        if await self.repository.kill_switch_active():
            return await self._revise(row, "blocked", "kill_switch_active")

        request = OlympusPromotionRequest(**row["request"])
        evidence = dict(request.evidence)
        minimum = int(os.getenv("AETHER_OLYMPUS_MIN_AGGREGATE", "5"))
        try:
            observed_threshold = int(evidence.get("aggregate_threshold", 0))
        except (TypeError, ValueError):
            observed_threshold = 0
        if observed_threshold < minimum:
            return await self._revise(row, "blocked", "aggregate_threshold_below_minimum")
        if not evidence.get("release_proof"):
            return await self._revise(row, "blocked", "release_proof_missing")

        decision = await evaluate_rights(
            action="derive",
            tenant_id=request.tenant_id,
            actor=ActorRef(
                kind="operator", id=request.requested_by, tenant_id=request.tenant_id,
            ),
            purpose="olympus_generalized_promotion",
            artifacts=[{
                "kind": "olympus_generalized_graph",
                "id": promotion_id,
                "tenant_id": request.tenant_id,
            }],
            envelope_refs=request.input_envelope_refs,
            source_grant_refs=request.source_grant_refs,
            policy_set_ref=request.policy_set_ref,
            destination={
                "kind": "olympus_plane",
                "id": "olympus_generalized_graph",
                "disclosure_level": "aggregate",
            },
            transform="promote_to_olympus_generalized_graph",
            metadata={
                "approval_refs": request.approval_refs,
                "transform_evidence": evidence,
                "promotion_id": promotion_id,
            },
        )
        if not decision.proceed:
            return await self._revise(
                row,
                "blocked",
                ",".join(decision.reason_codes) or "rights_denied",
                decision_id=decision.decision.decision_id if decision.decision else None,
            )

        output_ref = ArtifactRef(
            kind="olympus_generalized_graph",
            id=promotion_id,
        )
        output_envelope = await rights_authority.attach_artifact(AttachRightsEnvelope(
            artifact_ref=output_ref,
            primary_rights_class="olympus_generalized_intelligence",
            policy_set_ref=request.policy_set_ref,
            tenant_id=request.tenant_id,
            source_grant_refs=request.source_grant_refs,
            lineage_root_refs=request.input_envelope_refs,
            retention_class="olympus_generalized_indefinite",
            disclosure_ceiling="aggregate",
        ))

        mutation_ids: list[str] = []
        for mutation in request.graph_mutations:
            if await self.repository.kill_switch_active():
                return await self._revise(row, "blocked", "kill_switch_active", decision_id=decision.decision.decision_id if decision.decision else None)
            intent = self._mutation_intent(
                mutation,
                request,
                decision.decision.decision_id if decision.decision else None,
                output_envelope.envelope_id,
            )
            outcome = await get_mutation_gateway().apply(intent)
            if not outcome.applied:
                return await self._revise(
                    row, "blocked", "generalized_graph_mutation_blocked",
                    decision_id=decision.decision.decision_id if decision.decision else None,
                )
            mutation_ids.append(outcome.mutation_id)

        return await self._revise(
            row,
            "released",
            "released",
            decision_id=decision.decision.decision_id if decision.decision else None,
            output_envelope_id=output_envelope.envelope_id,
            mutation_ids=mutation_ids,
        )

    @staticmethod
    def _mutation_intent(
        mutation: dict[str, Any],
        request: OlympusPromotionRequest,
        decision_id: Optional[str],
        envelope_id: str,
    ) -> MutationIntent:
        kind = mutation.get("kind")
        properties = {
            **(mutation.get("properties") or {}),
            "rights_decision_id": decision_id,
            "rights_envelope_id": envelope_id,
            "rights_policy_set_ref": request.policy_set_ref,
            "rights_source_grant_refs": request.source_grant_refs,
        }
        if kind == "vertex":
            return MutationIntent(
                operation="node_created",
                tenant_id=request.tenant_id,
                vertex=Vertex(
                    vertex_type=mutation["vertex_type"],
                    vertex_id=mutation["vertex_id"],
                    properties=properties,
                ),
                actor_kind="operator",
                actor_id=request.requested_by,
                rights_decision_id=decision_id,
                rights_envelope_id=envelope_id,
                rights_policy_set_ref=request.policy_set_ref,
                rights_source_grant_refs=request.source_grant_refs,
                reason_code="olympus_generalized_release",
            )
        if kind == "edge":
            return MutationIntent(
                operation="edge_created",
                tenant_id=request.tenant_id,
                edge=Edge(
                    edge_type=mutation["edge_type"],
                    from_vertex_id=mutation["from_vertex_id"],
                    to_vertex_id=mutation["to_vertex_id"],
                    properties=properties,
                ),
                actor_kind="operator",
                actor_id=request.requested_by,
                rights_decision_id=decision_id,
                rights_envelope_id=envelope_id,
                rights_policy_set_ref=request.policy_set_ref,
                rights_source_grant_refs=request.source_grant_refs,
                reason_code="olympus_generalized_release",
            )
        raise ValueError("graph_mutations entries must have kind=vertex or kind=edge")

    async def _revise(
        self,
        row: dict[str, Any],
        status: str,
        reason: str,
        **fields: Any,
    ) -> dict[str, Any]:
        updated = {
            **row,
            "status": status,
            "reason": reason,
            "revision": int(row.get("revision", 1)) + 1,
            "updated_at": _now(),
            **fields,
        }
        await self.repository.append_promotion_revision(updated)
        return updated


olympus_generalized_gateway = OlympusGeneralizedGraphGateway()

__all__ = [
    "OlympusGeneralizedGraphGateway",
    "OlympusPromotionRequest",
    "olympus_generalized_gateway",
]
