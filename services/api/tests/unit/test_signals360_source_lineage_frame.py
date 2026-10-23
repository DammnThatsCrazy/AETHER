"""Signals360 composes exact event source metadata through the frame runtime."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from intelligence.signals.signals360_provider import (  # noqa: E402
    ObservationQualityRead,
    Signals360Provider,
)
from shared.intelligence_projections.contracts import (  # noqa: E402
    Experience360FrameRequest,
    Experience360PolicyDisposition,
    Experience360PolicyEvaluation,
    ProjectionContext,
    ProjectionSubject,
)
from shared.intelligence_projections.frame_runtime import (  # noqa: E402
    build_experience360_frame,
)

TENANT = "tenant-signals-source-lineage"


class ExactObservationSource:
    def __init__(self, row: dict[str, Any]) -> None:
        self.row = row
        self.calls: list[tuple[str, str]] = []

    async def observation_quality(self, *, tenant_id: str, observation_id: str):
        self.calls.append((tenant_id, observation_id))
        if tenant_id != TENANT or observation_id != self.row["provider_record_id"]:
            return ObservationQualityRead(None, True, True, "exact_sdk_observation_not_found")
        return ObservationQualityRead(self.row, True, True)


def _bronze_row(observation_id: str) -> dict[str, Any]:
    return {
        "id": "bronze-record-source-lineage",
        "tenant_id": TENANT,
        "provider_record_id": observation_id,
        "source": "sdk",
        "ingested_at": "2026-10-18T12:00:00Z",
        "payload": {
            "event_type": "track",
            "observation_envelope": {
                "tenancy": {"tenant_id": TENANT},
                "observation": {
                    "observation_id": observation_id,
                    "observation_type": "track",
                    "family": "core",
                    "schema_version": "observation-envelope/1.0.0",
                    "ingested_at": "2026-10-18T12:00:00Z",
                },
                "source": {
                    "source_type": "sdk",
                    "source_relationship": "first_party_application",
                    "ingress_path": "/v1/batch",
                },
                "provenance": {"adapter": "sdk", "adapter_version": "1.0.0"},
                "quality": {"validation_state": "gateway:accepted"},
            },
        },
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("subject_kind", ["event", "observation"])
async def test_signals360_composes_exact_source_inventory_with_evidence(
    subject_kind: str,
) -> None:
    observation_id = "event-signals-source-lineage-1"
    source = ExactObservationSource(_bronze_row(observation_id))
    provider = Signals360Provider(source=source)
    projection_calls: list[tuple[str, str, tuple[str, ...]]] = []

    class AllowPolicy:
        async def evaluate(self, request: Experience360FrameRequest):
            return Experience360PolicyEvaluation(
                surfaceId=request.surfaceId,
                tenantId=request.tenantId,
                evaluatedAt="2026-10-18T12:02:00Z",
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={
                    "source_inventory": Experience360PolicyDisposition(state="allowed")
                },
            )

    class Runtime:
        async def execute_projection(self, request, **kwargs):
            sections = tuple(request.includeSections or ())
            projection_calls.append((request.projectionId, request.subject.kind, sections))
            assert request.projectionId == "signals360"
            return await provider.project(
                request,
                ProjectionContext(
                    projectionId="signals360",
                    tenantId=request.tenantId,
                    registryState="in_flight",
                    dependencyState=[],
                    warnings=[],
                ),
            )

    request = Experience360FrameRequest(
        surfaceId="signals360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind=subject_kind, id=observation_id),
        requestedSlotIds=["source_inventory"],
        includeEvidence=True,
    )
    frame = await build_experience360_frame(
        request,
        policy_evaluator=AllowPolicy(),
        projection_runtime=Runtime(),
        generated_at="2026-10-18T12:03:00Z",
    )

    assert projection_calls == [("signals360", subject_kind, ("source_inventory",))]
    assert source.calls == [(TENANT, observation_id)]
    slot = frame.slots[0]
    assert slot.state == "degraded"
    assert slot.content is not None
    section_content = slot.content["sections"][0]["content"]
    assert section_content["coverage"] == "one_exact_sdk_observation"
    assert section_content["sources"][0]["sourceType"] == "sdk"
    assert section_content["sources"][0]["sourceRelationship"] == "first_party_application"
    assert {evidence.id for evidence in slot.evidenceRefs} == {observation_id}
    assert {
        item.sectionId for item in slot.provenance if item.sectionId is not None
    } == {"source_inventory"}
    assert frame.degradation.missingDependencies is None
