"""Agent360 business outcomes use exact canonical agent outcome lineage."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from graph.operational_intelligence.models import EntityRef, EvidenceRef  # noqa: E402
from journeys.measurement.outcome.contracts import OutcomeState  # noqa: E402
from journeys.measurement.outcome.provider import Outcome360Provider  # noqa: E402
from shared.backend_interpretation.primitives import OutcomeTruthRecord  # noqa: E402
from shared.backend_interpretation.stores import (  # noqa: E402
    OutcomeTruthStore,
    OutcomeTruthStoreReader,
)
from shared.intelligence_projections.contracts import (  # noqa: E402
    Experience360FrameRequest,
    Experience360PolicyDisposition,
    Experience360PolicyEvaluation,
    ProjectionSubject,
)
from shared.intelligence_projections.frame_runtime import (  # noqa: E402
    build_experience360_frame,
)
from shared.projection_engine.executor import ProjectionExecutor  # noqa: E402
from shared.projection_engine.runtime import ProjectionRuntime  # noqa: E402
from shared.intelligence_projections.registry import ProviderRegistry  # noqa: E402
from shared.store import InMemoryStore  # noqa: E402

TENANT = "tenant-agent-outcomes"
AGENT_ID = "agent-outcomes-1"


@pytest.mark.asyncio
async def test_outcome_truth_prediction_lookup_requires_exact_tenant_and_label_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import shared.backend_interpretation.stores as truth_stores

    backing = InMemoryStore("profile360-exact-prediction-outcomes")
    monkeypatch.setattr(truth_stores, "_kv", lambda _name: backing)
    store = OutcomeTruthStore()

    def record(outcome_id: str, tenant_id: str, version: str) -> OutcomeTruthRecord:
        return OutcomeTruthRecord(
            outcome_id=outcome_id,
            tenant_id=tenant_id,
            definition_ref="goal_achieved",
            subject=EntityRef(kind="user", id="profile-1"),
            state="final",
            prediction_id="ppout-exact-1",
            prediction_label_contract_version=version,
            observed_at="2026-10-30T12:00:00Z",
            evidence_refs=[EvidenceRef(id=f"event-{outcome_id}", type="event", source="silver_outcome_facts")],
        )

    await store.upsert(record("outcome-exact", TENANT, "profile-outcome-labels.v1"))
    await store.upsert(record("outcome-wrong-version", TENANT, "profile-outcome-labels.v2"))
    await store.upsert(record("outcome-wrong-tenant", "tenant-other", "profile-outcome-labels.v1"))

    rows, truncated, invalid = await store.list_for_prediction(
        TENANT, "ppout-exact-1", "profile-outcome-labels.v1", limit=10
    )

    assert [row.outcome_id for row in rows] == ["outcome-exact"]
    assert truncated is False
    assert invalid is False

    await backing.set(f"{TENANT}:outcome-malformed", {
        "outcome_id": "outcome-malformed",
        "tenant_id": TENANT,
        "definition_ref": "goal_achieved",
        "state": "not-a-state",
        "prediction_id": "ppout-exact-1",
        "prediction_label_contract_version": "profile-outcome-labels.v1",
    })
    rows, _truncated, invalid = await store.list_for_prediction(
        TENANT, "ppout-exact-1", "profile-outcome-labels.v1", limit=10
    )
    assert [row.outcome_id for row in rows] == ["outcome-exact"]
    assert invalid is True


@pytest.mark.asyncio
async def test_agent360_business_outcomes_reads_exact_agent_truth_with_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import shared.backend_interpretation.stores as truth_stores

    backing = InMemoryStore("experience360-agent-outcomes")
    monkeypatch.setattr(truth_stores, "_kv", lambda _name: backing)
    store = OutcomeTruthStore()
    evidence = EvidenceRef(
        id="agent-outcome-evidence-1",
        type="event",
        source="agent_execution_outcomes",
        observedAt="2026-10-18T12:00:00Z",
    )

    def record(
        outcome_id: str,
        tenant_id: str,
        entity_kind: str,
        evidence_id: str,
    ) -> OutcomeTruthRecord:
        return OutcomeTruthRecord(
            outcome_id=outcome_id,
            tenant_id=tenant_id,
            definition_ref="agent_task_completed",
            subject=EntityRef(kind=entity_kind, id=AGENT_ID),
            state="final",
            value_state="present",
            value_amount="1",
            value_currency="count",
            evidence_refs=[evidence.model_copy(update={"id": evidence_id})],
            source_event_ids=[f"event-{outcome_id}"],
            observed_at="2026-10-18T12:00:00Z",
            updated_at="2026-10-18T12:00:01Z",
        )

    await store.upsert(record("agent-outcome-valid", TENANT, "agent", evidence.id))
    await store.upsert(record("agent-outcome-wrong-type", TENANT, "user", "user-evidence"))
    await store.upsert(record("agent-outcome-wrong-tenant", "tenant-other", "agent", "foreign-evidence"))

    outcome_reader = OutcomeTruthStoreReader(store=store)
    provider_registry = ProviderRegistry()
    provider_registry.register(
        Outcome360Provider(outcome_store=outcome_reader),
        source="test:outcome-truth-store-reader",
    )
    projection_runtime = ProjectionRuntime(
        executor=ProjectionExecutor(registry=provider_registry)
    )

    class AllowPolicy:
        async def evaluate(self, request: Experience360FrameRequest):
            assert request.subject == ProjectionSubject(kind="agent", id=AGENT_ID)
            return Experience360PolicyEvaluation(
                surfaceId=request.surfaceId,
                tenantId=request.tenantId,
                evaluatedAt="2026-10-18T12:01:00Z",
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={
                    "business_outcomes": Experience360PolicyDisposition(state="allowed")
                },
            )

    frame = await build_experience360_frame(
        Experience360FrameRequest(
            surfaceId="agent360",
            tenantId=TENANT,
            subject=ProjectionSubject(kind="agent", id=AGENT_ID),
            requestedSlotIds=["business_outcomes"],
            includeEvidence=True,
        ),
        policy_evaluator=AllowPolicy(),
        projection_runtime=projection_runtime,
        generated_at="2026-10-18T12:02:00Z",
    )

    slot = frame.slots[0]
    assert slot.state == "available"
    assert slot.content is not None
    outcome_section = next(
        item for item in slot.content["sections"] if item["sectionId"] == "outcomes"
    )
    assert [row["id"] for row in outcome_section["content"]["outcomes"]] == [
        "agent-outcome-valid"
    ]
    assert [ref.id for ref in slot.evidenceRefs] == [evidence.id]
    assert {item.projectionId for item in slot.provenance} == {"outcome360"}
    assert {item.sectionId for item in slot.provenance} == {"evidence", "outcomes"}
