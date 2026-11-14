"""Route wiring for server-owned Experience 360 slot metadata."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from shared.intelligence_projections.contracts import (
    Experience360Freshness,
    Experience360PolicyEvaluation,
    Experience360PolicyDisposition,
    Experience360Quality,
)
from shared.intelligence_projections.routes import (
    Experience360FrameBody,
    post_experience360_frame,
)


class _PolicyEvaluator:
    async def evaluate(self, request):
        return Experience360PolicyEvaluation(
            surfaceId=request.surfaceId,
            tenantId=request.tenantId,
            evaluatedAt="2026-10-18T12:00:00Z",
            frameDisposition=Experience360PolicyDisposition(state="allowed"),
        )


@pytest.mark.asyncio
async def test_frame_route_passes_server_freshness_and_quality_to_runtime(monkeypatch) -> None:
    freshness = {
        "identity": Experience360Freshness(
            state="fresh",
            sourceAsOf="2026-10-18T11:59:00Z",
            evaluatedAt="2026-10-18T12:00:00Z",
        )
    }
    quality = {
        "identity": Experience360Quality(
            state="adequate",
            reasonCodes=[],
        )
    }
    captured = {}

    async def fake_build(request, **kwargs):
        captured["request"] = request
        captured.update(kwargs)
        return SimpleNamespace(model_dump=lambda **_: {"surfaceId": request.surfaceId})

    monkeypatch.setattr(
        "shared.intelligence_projections.routes.build_experience360_frame", fake_build
    )

    tenant = SimpleNamespace(
        tenant_id="tenant-route-test",
        require_permission=lambda permission: None,
    )
    app_state = SimpleNamespace(
        experience360_policy_evaluator=_PolicyEvaluator(),
        experience360_freshness_by_slot=freshness,
        experience360_quality_by_slot=quality,
    )
    request = SimpleNamespace(
        state=SimpleNamespace(tenant=tenant),
        app=SimpleNamespace(state=app_state),
    )
    body = Experience360FrameBody(
        surfaceId="agent360",
        subject={"kind": "agent", "id": "agent-route-test"},
        requestedSlotIds=["identity"],
    )

    response = await post_experience360_frame(body, request)

    assert response == {"surfaceId": "agent360"}
    assert captured["request"].tenantId == "tenant-route-test"
    assert captured["freshness_by_slot"] is freshness
    assert captured["quality_by_slot"] is quality
