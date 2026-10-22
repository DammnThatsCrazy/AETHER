"""Contract-level runtime proof for every product 360 and declared subject."""

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

from graph.operational_intelligence.models import EvidenceRef  # noqa: E402
from identity.account360_provider import (  # noqa: E402
    Account360Provider,
    AccountIdentityRead,
)
from identity.identity.identity360_provider import (  # noqa: E402
    Identity360Result,
    Identity360Slot,
)
from shared.intelligence_projections.contracts import (  # noqa: E402
    Experience360FrameRequest,
    Experience360PolicyEvaluation,
    Experience360PolicyDisposition,
    ProjectionResult,
    ProjectionSection,
    ProjectionSubject,
)
from shared.intelligence_projections.frame_runtime import (  # noqa: E402
    build_experience360_frame,
)
from shared.intelligence_projections.routes import (  # noqa: E402
    Experience360FrameBody,
    post_experience360_frame,
)
from shared.intelligence_projections.generated_registry import (  # noqa: E402
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
    PRODUCT_360_SURFACE_DEFINITIONS,
)


TENANT_ID = "tenant-360-matrix"
GENERATED_AT = "2026-10-18T12:00:00Z"
ACCOUNT_EVIDENCE = EvidenceRef(
    id="matrix-account-entity",
    type="entity",
    source="entity_registry",
    observedAt=GENERATED_AT,
)


class _AllowedPolicy:
    def __init__(self, events: list[tuple[str, str, str]]) -> None:
        self.events = events

    async def evaluate(self, request: Experience360FrameRequest) -> Experience360PolicyEvaluation:
        self.events.append(("policy", request.surfaceId, request.subject.kind))
        return Experience360PolicyEvaluation(
            surfaceId=request.surfaceId,
            tenantId=request.tenantId,
            evaluatedAt=GENERATED_AT,
            frameDisposition=Experience360PolicyDisposition(state="allowed"),
        )


class _EmptyProjectionRuntime:
    """Return a known empty result for each explicitly requested projection section."""

    def __init__(self, events: list[tuple[str, str, str]]) -> None:
        self.events = events
        self.calls: list[tuple[str, str, tuple[str, ...]]] = []

    async def execute_projection(self, request, **_kwargs) -> ProjectionResult:
        section_ids = tuple(sorted(request.includeSections or []))
        self.calls.append((request.projectionId, request.subject.kind, section_ids))
        self.events.append(("projection", request.projectionId, request.subject.kind))
        return ProjectionResult(
            projectionId=request.projectionId,
            tenantId=request.tenantId,
            contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
            sections=[ProjectionSection(id=section_id, state="empty") for section_id in section_ids],
            claims=[],
            dependencyState=[],
            generatedAt=GENERATED_AT,
            asOf=None,
            degradedReasons=[],
        )


class _AccountSource:
    def __init__(self, events: list[tuple[str, str, str]]) -> None:
        self.events = events

    async def canonical_entity(self, tenant_id: str, entity_id: str) -> AccountIdentityRead:
        self.events.append(("account_identity", tenant_id, entity_id))
        return AccountIdentityRead("resolved", evidence_refs=(ACCOUNT_EVIDENCE,))


class _IdentityReader:
    def __init__(self, events: list[tuple[str, str, str]]) -> None:
        self.events = events

    async def read(
        self,
        tenant_id: str,
        subject_kind: str,
        subject_id: str,
        *,
        requested_slot_ids: set[str],
    ) -> Identity360Result:
        self.events.append(("identity_read", subject_kind, subject_id))
        return Identity360Result(
            tenant_id=tenant_id,
            subject_kind=subject_kind,
            subject_id=subject_id,
            state="available",
            slots=tuple(
                Identity360Slot(id=slot_id, state="empty", content={})
                for slot_id in sorted(requested_slot_ids)
            ),
            generated_at=GENERATED_AT,
        )


def _expected_projection_sections(
    surface: dict[str, Any], subject_kind: str
) -> dict[str, tuple[str, ...]]:
    sections: dict[str, set[str]] = {}
    for slot in surface["domainSlots"]:
        for binding in slot.get("projectionBindings", []):
            if subject_kind not in binding.get("subjectKinds", []):
                continue
            sections.setdefault(binding["projectionId"], set()).update(
                binding.get("sectionIds", [])
            )
    return {projection_id: tuple(sorted(section_ids)) for projection_id, section_ids in sections.items()}


@pytest.mark.asyncio
async def test_every_product_surface_and_subject_runs_only_its_declared_provider_paths() -> None:
    """Exercise policy → provider selection → composition across the 18-surface matrix."""

    direct_identity_slots = {
        slot_id
        for binding in PRODUCT_360_SURFACE_DEFINITIONS["identity360"]["directProviderBindings"]
        for slot_id in binding["domainSlotIds"]
    }
    direct_account_slots = {
        slot_id
        for binding in PRODUCT_360_SURFACE_DEFINITIONS["account360"]["directProviderBindings"]
        for slot_id in binding["domainSlotIds"]
    }
    checked_cases = 0

    for surface_id, surface in PRODUCT_360_SURFACE_DEFINITIONS.items():
        for subject_kind in surface["subjectKinds"]:
            checked_cases += 1
            events: list[tuple[str, str, str]] = []
            runtime = _EmptyProjectionRuntime(events)
            request = Experience360FrameRequest(
                surfaceId=surface_id,
                tenantId=TENANT_ID,
                subject=ProjectionSubject(
                    kind=subject_kind,
                    id=f"{surface_id}-{subject_kind}-subject",
                ),
                includeEvidence=True,
            )

            kwargs: dict[str, Any] = {}
            if surface_id == "account360":
                kwargs["account360_provider"] = Account360Provider(
                    source=_AccountSource(events)
                )
            if surface_id == "identity360":
                kwargs["identity360_provider"] = _IdentityReader(events)

            frame = await build_experience360_frame(
                request,
                policy_evaluator=_AllowedPolicy(events),
                projection_runtime=runtime,
                generated_at=GENERATED_AT,
                **kwargs,
            )

            assert frame.surfaceId == surface_id
            assert frame.tenantId == TENANT_ID
            assert frame.subject == request.subject
            assert frame.ownsCanonicalTruth is False
            assert {slot.id for slot in frame.slots} == {
                slot["id"] for slot in surface["domainSlots"]
            }
            assert events and events[0] == ("policy", surface_id, subject_kind)

            actual_calls = {
                projection_id: section_ids
                for projection_id, _kind, section_ids in runtime.calls
            }
            assert actual_calls == _expected_projection_sections(surface, subject_kind)
            assert all(call_kind == subject_kind for _, call_kind, _ in runtime.calls)

            expected_slots = {
                slot["id"]: slot
                for slot in surface["domainSlots"]
            }
            for slot in frame.slots:
                # The generic projection path returns a known empty result. A slot
                # with no applicable projection is explicitly unknown; Identity360's
                # direct reader supplies the source-aligned identity slots.
                has_compatible_binding = any(
                    subject_kind in binding.get("subjectKinds", [])
                    for binding in expected_slots[slot.id].get("projectionBindings", [])
                )
                direct_identity_applies = (
                    surface_id == "identity360" and slot.id in direct_identity_slots
                )
                direct_account_applies = (
                    surface_id == "account360"
                    and subject_kind == "entity"
                    and slot.id in direct_account_slots
                )
                if not has_compatible_binding and not direct_identity_applies and not direct_account_applies:
                    assert slot.state == "unknown", (
                        surface_id,
                        subject_kind,
                        slot.id,
                        slot.reasonCodes,
                    )
                    assert (
                        "projection_binding_subject_kind_unsupported" in slot.reasonCodes
                        or "projection_result_missing" in slot.reasonCodes
                        or "slot_provider_not_connected" in slot.reasonCodes
                    )
                assert slot.state in {
                    "empty",
                    "unknown",
                    "degraded",
                    "unavailable",
                    "missing",
                    "suppressed",
                }

    assert checked_cases > len(PRODUCT_360_SURFACE_DEFINITIONS)


@pytest.mark.asyncio
async def test_mounted_frame_route_enforces_tenant_policy_and_composes_every_surface() -> None:
    """Exercise the authenticated HTTP boundary for all current surfaces/subjects."""

    checked_cases = 0
    for surface_id, surface in PRODUCT_360_SURFACE_DEFINITIONS.items():
        for subject_kind in surface["subjectKinds"]:
            checked_cases += 1
            events: list[tuple[str, str, str]] = []
            runtime = _EmptyProjectionRuntime(events)
            app_state = type(
                "Experience360TestState",
                (),
                {
                    "experience360_policy_evaluator": _AllowedPolicy(events),
                    "experience360_projection_runtime": runtime,
                },
            )()
            if surface_id == "account360":
                app_state.experience360_account360_provider = Account360Provider(
                    source=_AccountSource(events)
                )
            if surface_id == "identity360":
                app_state.experience360_identity360_provider = _IdentityReader(events)

            tenant = type(
                "AuthenticatedTenant",
                (),
                {
                    "tenant_id": TENANT_ID,
                    "require_permission": lambda _self, _permission: None,
                },
            )()
            request = type(
                "Experience360Request",
                (),
                {
                    "state": type("RequestState", (), {"tenant": tenant})(),
                    "app": type("App", (), {"state": app_state})(),
                },
            )()
            body = Experience360FrameBody(
                surfaceId=surface_id,
                subject={"kind": subject_kind, "id": f"{surface_id}-{subject_kind}-subject"},
            )

            response = await post_experience360_frame(body, request)

            assert response["surfaceId"] == surface_id
            assert response["tenantId"] == TENANT_ID
            assert response["subject"] == {
                "kind": subject_kind,
                "id": f"{surface_id}-{subject_kind}-subject",
            }
            assert response["ownsCanonicalTruth"] is False
            assert {slot["id"] for slot in response["slots"]} == {
                slot["id"] for slot in surface["domainSlots"]
            }
            assert events and events[0] == ("policy", surface_id, subject_kind)
            assert {
                projection_id: section_ids
                for projection_id, _kind, section_ids in runtime.calls
            } == _expected_projection_sections(surface, subject_kind)
            assert all(call_kind == subject_kind for _, call_kind, _ in runtime.calls)

    assert checked_cases > len(PRODUCT_360_SURFACE_DEFINITIONS)
