"""Signals360 routes source risk through exact Risk360 subject reads."""

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

from intelligence.risk360.provider import Risk360Provider  # noqa: E402
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

TENANT = "tenant-signals-source-risk"
SOURCE_ID = "provider:crm"


class ExactSourceRiskReader:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def latest_assessment(
        self, *, tenant_id: str, subject: ProjectionSubject
    ) -> dict[str, Any]:
        self.calls.append(("assessment", tenant_id, subject.kind + ":" + subject.id))
        return {
            "assessment_id": "risk-source-assessment-1",
            "tenant_id": tenant_id,
            "subject_kind": subject.kind,
            "subject_id": subject.id,
            "dimensions": ["identity"],
            "vector": {
                "components": [
                    {
                        "dimension": "identity",
                        "state": "observed",
                        "score": 0.65,
                        "claim_state": "observed",
                        "confidence": 0.9,
                        "evidence_refs": [
                            {
                                "id": "source-risk-evidence-1",
                                "type": "event",
                                "source": "source_trust_detector",
                            }
                        ],
                    }
                ]
            },
            "claim_state": "derived",
            "confidence": 0.8,
            "evidence_refs": [
                {
                    "id": "source-risk-assessment-evidence-1",
                    "type": "event",
                    "source": "risk_assessments",
                }
            ],
            "assessed_at": "2026-10-18T12:00:00Z",
        }

    async def signals(self, *, tenant_id: str, subject: ProjectionSubject) -> list[dict[str, Any]]:
        self.calls.append(("signals", tenant_id, subject.kind + ":" + subject.id))
        return [
            {
                "signal_id": "source-risk-signal-1",
                "tenant_id": tenant_id,
                "subject_kind": subject.kind,
                "subject_id": subject.id,
                "risk_dimension": "identity",
                "claim_state": "inferred",
                "confidence": 0.7,
                "evidence_refs": [
                    {
                        "id": "source-risk-signal-evidence-1",
                        "type": "event",
                        "source": "source_trust_detector",
                    }
                ],
                "source": "source_trust_detector",
                "detector_version": "1",
                "observed_at": "2026-10-18T11:59:00Z",
                "score": 0.6,
            }
        ]


@pytest.mark.asyncio
async def test_signals360_source_risk_slot_uses_exact_tenant_source_risk_records() -> None:
    reader = ExactSourceRiskReader()
    provider = Risk360Provider(sources=reader)
    projection_calls: list[tuple[str, str, str]] = []

    class AllowPolicy:
        async def evaluate(self, request: Experience360FrameRequest):
            return Experience360PolicyEvaluation(
                surfaceId=request.surfaceId,
                tenantId=request.tenantId,
                evaluatedAt="2026-10-18T12:02:00Z",
                frameDisposition=Experience360PolicyDisposition(state="allowed"),
                slotDispositions={
                    "risk_signals": Experience360PolicyDisposition(state="allowed")
                },
            )

    class Runtime:
        async def execute_projection(self, request, **kwargs):
            projection_calls.append(
                (request.projectionId, request.tenantId, request.subject.kind + ":" + request.subject.id)
            )
            assert request.projectionId == "risk360"
            return await provider.project(
                request,
                ProjectionContext(
                    projectionId="risk360",
                    tenantId=request.tenantId,
                    registryState="implemented",
                    dependencyState=[],
                    warnings=[],
                ),
            )

    request = Experience360FrameRequest(
        surfaceId="signals360",
        tenantId=TENANT,
        subject=ProjectionSubject(kind="source", id=SOURCE_ID),
        requestedSlotIds=["risk_signals"],
        includeEvidence=True,
    )
    frame = await build_experience360_frame(
        request,
        policy_evaluator=AllowPolicy(),
        projection_runtime=Runtime(),
        generated_at="2026-10-18T12:03:00Z",
    )

    assert projection_calls == [("risk360", TENANT, f"source:{SOURCE_ID}")]
    assert reader.calls == [
        ("assessment", TENANT, f"source:{SOURCE_ID}"),
        ("signals", TENANT, f"source:{SOURCE_ID}"),
    ]
    slot = frame.slots[0]
    assert slot.state == "degraded"
    assert slot.content is not None
    assert {ref.id for ref in slot.evidenceRefs} == {
        "source-risk-assessment-evidence-1",
        "source-risk-evidence-1",
        "source-risk-signal-evidence-1",
    }
    assert {item.projectionId for item in slot.provenance} == {"risk360"}
    assert "slot_contains_partial_evidence" in slot.reasonCodes
