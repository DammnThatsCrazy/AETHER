"""Gold intelligence endpoints: a Silver outage must not read as zero metrics.

`_query_silver` used to swallow every store failure into `[]`, so all six gold
endpoints (and /account-health) served confidently-zero metrics during an
outage. These tests pin the honest contract: the response carries
`source_status` using the profile360/campaign vocabulary — ``missing`` (store
not consulted / failed), ``empty`` (consulted, genuinely none), ``available``
(has rows).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from services.intelligence import routes as intel_routes


class _Tenant:
    def __init__(self, tenant_id: str = "tenant-a"):
        self.tenant_id = tenant_id

    def require_permission(self, permission: str) -> None:
        assert permission == "read"


def _req(tenant_id: str = "tenant-a"):
    return SimpleNamespace(state=SimpleNamespace(tenant=_Tenant(tenant_id)))


_GOLD_HANDLERS = [
    "get_revenue_intelligence",
    "get_experience_intelligence",
    "get_exposure_intelligence",
    "get_agent_intelligence",
    "get_integration_intelligence",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("handler_name", _GOLD_HANDLERS)
async def test_gold_endpoint_reports_missing_when_silver_unavailable(handler_name):
    handler = getattr(intel_routes, handler_name)
    with patch("repositories.repos.AnalyticsRepository") as MockRepo:
        MockRepo.return_value.query_silver = AsyncMock(
            side_effect=RuntimeError("silver store down")
        )
        result = await handler(_req(), entity_id=None, window="30d")
    assert result["data"]["source_status"] == "missing"


@pytest.mark.asyncio
@pytest.mark.parametrize("handler_name", _GOLD_HANDLERS)
async def test_gold_endpoint_reports_empty_when_consulted_and_none(handler_name):
    handler = getattr(intel_routes, handler_name)
    with patch("repositories.repos.AnalyticsRepository") as MockRepo:
        MockRepo.return_value.query_silver = AsyncMock(return_value=[])
        result = await handler(_req(), entity_id=None, window="30d")
    assert result["data"]["source_status"] == "empty"


@pytest.mark.asyncio
async def test_gold_endpoint_reports_available_with_rows():
    rows = [{"tenant_id": "tenant-a", "amount": 100, "payload": {}}]
    with patch("repositories.repos.AnalyticsRepository") as MockRepo:
        MockRepo.return_value.query_silver = AsyncMock(return_value=rows)
        result = await intel_routes.get_revenue_intelligence(
            _req(), entity_id=None, window="30d"
        )
    assert result["data"]["source_status"] == "available"
    assert result["data"]["metrics"]["record_count"] == 1


# The customer_success module does not define CustomerSuccessAccountRepository
# — the route's import of it used to sit outside the try and 500'd every call.
# create=True injects the attribute so the success/failure paths past the
# import are testable; the un-patched test below pins the import-failure path.


@pytest.mark.asyncio
async def test_account_health_reports_missing_when_account_store_unavailable():
    """Covers both today's reality (the repository class does not exist, so
    the guarded import fails) and, via the silver mock, that the response is
    still an honest 200 with source_status 'missing' rather than a 500."""
    with patch("repositories.repos.AnalyticsRepository") as MockRepo:
        MockRepo.return_value.query_silver = AsyncMock(return_value=[])
        result = await intel_routes.get_account_health(
            _req(), entity_id=None, window="30d"
        )
    assert result["data"]["source_status"] == "missing"


@pytest.mark.asyncio
async def test_account_health_reports_missing_when_silver_unavailable():
    with patch(
        "services.intelligence.customer_success.CustomerSuccessAccountRepository",
        create=True,
    ) as MockCS, patch("repositories.repos.AnalyticsRepository") as MockRepo:
        MockCS.return_value.get_for_tenant = AsyncMock(
            return_value={"health_score": 0.8, "lifecycle_stage": "value_proven"}
        )
        MockRepo.return_value.query_silver = AsyncMock(
            side_effect=RuntimeError("silver store down")
        )
        result = await intel_routes.get_account_health(
            _req(), entity_id=None, window="30d"
        )
    assert result["data"]["source_status"] == "missing"


@pytest.mark.asyncio
async def test_account_health_reports_available_when_both_sources_answer():
    with patch(
        "services.intelligence.customer_success.CustomerSuccessAccountRepository",
        create=True,
    ) as MockCS, patch("repositories.repos.AnalyticsRepository") as MockRepo:
        MockCS.return_value.get_for_tenant = AsyncMock(
            return_value={"health_score": 0.8, "lifecycle_stage": "value_proven"}
        )
        MockRepo.return_value.query_silver = AsyncMock(return_value=[])
        result = await intel_routes.get_account_health(
            _req(), entity_id=None, window="30d"
        )
    assert result["data"]["source_status"] == "available"
    assert result["data"]["metrics"]["health_score"] == 0.8
