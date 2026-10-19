"""Signals360 composes exact Identity360 lineage for entity and agent sources."""

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

from connectors.provider_runtime.source360_provider import Source360Provider  # noqa: E402
from graph.operational_intelligence.models import EvidenceRef  # noqa: E402
from identity.identity.identity360_provider import (  # noqa: E402
    Identity360Result,
    Identity360Slot,
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


class IdentityLineageReader:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def read(self, tenant_id: str, subject_kind: str, subject_id: str):
        self.calls.append((tenant_id, subject_kind, subject_id))
        evidence = EvidenceRef(
            id=f"identity-source-{subject_id}",
            type="entity",
            source="identity_source_identities",
            observedAt="2026-10-18T12:00:00Z",
        )
        return Identity360Result(
            tenant_id=tenant_id,
            subject_kind=subject_kind,
            subject_id=subject_id,
            state="available",
            slots=(
                Identity360Slot(
                    id="source_identifier_lineage",
                    state="available",
                    content={
                        "sourceIdentities": [
                            {"id": evidence.id, "sourceNamespace": "crm.contacts"}
                        ],
                        "coverage": {
                            "sourceIdentities": {
                                "state": "available",
                                "returned": 1,
                                "truncated": False,
                            }
                        },
                    },
                    evidence_refs=(evidence,),
                ),
            ),
            generated_at="2026-10-18T12:01:00Z",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("subject_kind", "subject_id"),
    [("entity", "entity-signal-1"), ("agent", "agent-signal-1")],
)
async def test_signals360_routes_identity_lineage_without_claiming_provider_health(
    subject_kind: str, subject_id: str
) -> None:
    identity_reader = IdentityLineageReader()
    source_provider = Source360Provider(
        source=object(), identity_lineage_reader=identity_reader
    )
    projection_calls: list[tuple[str, str, tuple[str, ...]]] = []

    class AllowPolicy:
        async def evaluate(self, request: Experience360FrameRequest):
            return Experience360PolicyEvaluation(
                surfaceId=request.surfaceId,
                tenantId=request.tenantId,
                evaluatedAt="2026-10-18T12:02:00Z",
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={
                    "source_signals_and_coverage": Experience360PolicyDisposition(
                        state="allowed"
                    )
                },
            )

    class Runtime:
        async def execute_projection(self, request, **kwargs):
            sections = tuple(request.includeSections or ())
            projection_calls.append((request.projectionId, request.subject.kind, sections))
            assert request.projectionId == "source360"
            return await source_provider.project(
                request,
                ProjectionContext(
                    projectionId="source360",
                    tenantId=request.tenantId,
                    registryState="in_flight",
                    dependencyState=[],
                    warnings=[],
                ),
            )

    request = Experience360FrameRequest(
        surfaceId="signals360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind=subject_kind, id=subject_id),
        requestedSlotIds=["source_signals_and_coverage"],
        includeEvidence=True,
    )
    frame = await build_experience360_frame(
        request,
        policy_evaluator=AllowPolicy(),
        projection_runtime=Runtime(),
        generated_at="2026-10-18T12:03:00Z",
    )

    assert projection_calls == [
        (
            "source360",
            subject_kind,
            ("coverage", "evidence", "health", "summary"),
        )
    ]
    assert identity_reader.calls == [(TENANT, subject_kind, subject_id)]
    slot = frame.slots[0]
    assert slot.state == "degraded"
    assert slot.content is not None
    assert {evidence.id for evidence in slot.evidenceRefs} == {
        f"identity-source-{subject_id}"
    }
    assert {item.sectionId for item in slot.provenance} == {
        "coverage",
        "evidence",
        "health",
        "summary",
    }
    health_provenance = next(item for item in slot.provenance if item.sectionId == "health")
    assert health_provenance.sourceState == "unknown"
    assert "slot_contains_partial_evidence" in slot.reasonCodes
    assert frame.degradation.missingDependencies is None
