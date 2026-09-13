"""Route contract for tenant-scoped referral performance reporting."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.measurement.routes import attribution


def _request(tenant_id: str = "tenant-a") -> SimpleNamespace:
    return SimpleNamespace(
        state=SimpleNamespace(tenant=SimpleNamespace(tenant_id=tenant_id))
    )


def test_referral_performance_route_is_registered() -> None:
    route_methods = {
        (route.path, method)
        for route in attribution.router.routes
        for method in (route.methods or set())
    }

    assert ("/v1/attribution/referral-performance", "GET") in route_methods


@pytest.mark.asyncio
async def test_referral_performance_forwards_tenant_and_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
    end_at = datetime(2026, 8, 1, tzinfo=timezone.utc)
    repo = SimpleNamespace(
        referral_performance=AsyncMock(
            return_value={"rows": [{"ai_provider": "openai"}], "row_count": 1}
        )
    )
    monkeypatch.setattr(attribution, "_run_repo", repo)

    response = await attribution.referral_performance(
        _request(),
        start_at=start_at,
        end_at=end_at,
        campaign_id="campaign-a",
        ai_provider="openai",
        ai_product="chatgpt",
        referral_mediation_type="ai_mediated_human_referral",
        source_class="ai_referral",
        limit=50,
    )

    repo.referral_performance.assert_awaited_once_with(
        "tenant-a",
        start_date=start_at,
        end_date=end_at,
        campaign_id="campaign-a",
        ai_provider="openai",
        ai_product="chatgpt",
        referral_mediation_type="ai_mediated_human_referral",
        source_class="ai_referral",
        limit=50,
    )
    assert response["data"]["row_count"] == 1
    assert response["data"]["rows"][0]["ai_provider"] == "openai"
