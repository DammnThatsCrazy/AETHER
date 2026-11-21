"""The 360 catalog is wired: every projection has a provider, every surface builds,
and no provider cites an authority its catalog slot does not declare.

This is the permanent form of the catalog audit. It boots the real API (so
provider registration is the production one), builds a frame for every product
surface with an allow-all policy in an empty tenant, and checks the composition
reasons. Empty tenants legitimately yield empty/unknown slots; what must never
appear is a catalog/provider mismatch that would drop a slot even with data.
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[3] / "services" / "api"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests")

# The subject kind each surface is built for: the kind its slots are bound to.
SURFACE_SUBJECTS = {
    "agent360": "agent", "execution360": "agent", "episode360": "episode", "profile360": "entity",
    "identity360": "entity", "journey360": "journey", "communications360": "profile", "risk360": "entity",
    "value360": "campaign", "social360": "entity", "campaign360": "campaign", "signals360": "event",
    "account360": "entity", "location360": "entity", "workflow360": "run", "memory360": "entity",
    "commerce360": "product", "support360": "support_case",
}
CATALOG_DEFECTS = {
    "projection_section_authority_refs_invalid",
    "invalid_projection_section_binding",
    "section_binding_unresolved",
    "freshness_threshold_not_configured",
}


class _AllowAll:
    async def evaluate(self, request):
        from shared.intelligence_projections.contracts import (
            Experience360PolicyDisposition,
            Experience360PolicyEvaluation,
        )
        from shared.intelligence_projections.generated_registry import PRODUCT_360_SURFACE_DEFINITIONS

        now = datetime.now(timezone.utc).isoformat()
        allow = Experience360PolicyDisposition(state="allowed", evaluatedAt=now)
        slots = PRODUCT_360_SURFACE_DEFINITIONS[request.surfaceId]["domainSlots"]
        return Experience360PolicyEvaluation(
            surfaceId=request.surfaceId, tenantId=request.tenantId, evaluatedAt=now,
            frameDisposition=allow, slotDispositions={s["id"]: allow for s in slots},
        )


@pytest.fixture(scope="module")
def frames():
    from fastapi.testclient import TestClient

    import main
    from shared.intelligence_projections.contracts import Experience360FrameRequest, ProjectionSubject
    from shared.intelligence_projections.frame_runtime import build_experience360_frame
    from shared.intelligence_projections.generated_registry import PRODUCT_360_SURFACE_DEFINITIONS
    from shared.intelligence_projections.registry import projection_registry

    built: dict[str, dict] = {}
    with TestClient(main.app):
        state = main.app.state
        registered = set(getattr(projection_registry, "_providers", {}))

        async def build_all():
            for surface_id in PRODUCT_360_SURFACE_DEFINITIONS:
                request = Experience360FrameRequest(
                    surfaceId=surface_id, tenantId="catalog-wiring-tenant",
                    subject=ProjectionSubject(kind=SURFACE_SUBJECTS[surface_id], id="catalog-wiring-subject"),
                )
                frame = await build_experience360_frame(
                    request, policy_evaluator=_AllowAll(),
                    projection_runtime=getattr(state, "experience360_projection_runtime", None),
                )
                built[surface_id] = frame.model_dump(mode="json", exclude_none=True)

        asyncio.run(build_all())
    return {"registered": registered, "frames": built}


def test_every_catalog_projection_has_a_registered_provider(frames):
    from shared.intelligence_projections.generated_registry import INTELLIGENCE_PROJECTION_DEFINITIONS

    missing = sorted(set(INTELLIGENCE_PROJECTION_DEFINITIONS) - frames["registered"])
    assert missing == [], f"catalog projections with no provider: {missing}"


def test_every_surface_in_the_catalog_has_a_subject_and_builds(frames):
    from shared.intelligence_projections.generated_registry import PRODUCT_360_SURFACE_DEFINITIONS

    assert set(PRODUCT_360_SURFACE_DEFINITIONS) == set(SURFACE_SUBJECTS)
    for surface_id, frame in frames["frames"].items():
        assert frame.get("slots"), f"{surface_id} built no slots"


def test_no_slot_is_dropped_by_a_catalog_provider_mismatch(frames):
    defects = []
    for surface_id, frame in frames["frames"].items():
        slots = frame["slots"]
        items = slots.items() if isinstance(slots, dict) else ((s.get("id"), s) for s in slots)
        for slot_id, slot in items:
            for code in set(slot.get("reasonCodes") or []) & CATALOG_DEFECTS:
                defects.append(f"{surface_id}.{slot_id}: {code}")
    assert defects == [], "\n".join(sorted(defects))
