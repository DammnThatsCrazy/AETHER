"""Focused contract checks for computed-result observability in Economic360."""

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

from shared.intelligence_projections import (  # noqa: E402
    ProjectionRequest,
    ProjectionSubject,
    ProviderRegistry,
)
from value.economic.economic360_provider import Economic360Provider  # noqa: E402


class ComputedResultSource:
    def __init__(self, records: list[dict]) -> None:
        self._records = records

    async def records(self, *, tenant_id: str, subject: ProjectionSubject) -> list[dict]:
        return list(self._records)

    async def is_canonical_campaign(self, tenant_id: str, campaign_id: str) -> bool:
        return (tenant_id, campaign_id) == ("tenant-a", "campaign-a")


def _computed_record(
    *,
    evidence_id: str,
    metric: str,
    status: str,
    computed_at: str | None,
    amount: str,
) -> dict:
    record = {
        "tenant_id": "tenant-a",
        "amount": amount,
        "currency": "USD",
        "value_usd": amount,
        "metric_kind": "flow",
        "_source": f"computed_results:{metric}",
        "_evidence_id": evidence_id,
        "_evidence_type": "model_output",
        "_evidence_source": "services/api/value/economic/computed_results",
        "_evidence_uri": f"store://computed_results/{metric}",
        "_metric_name": metric,
        "_result_status": status,
    }
    if computed_at is not None:
        record["_computed_at"] = computed_at
    return record


@pytest.mark.asyncio
async def test_computed_metric_exposes_status_timestamp_coverage_and_freshness() -> None:
    source = ComputedResultSource(
        [
            _computed_record(
                evidence_id="old-spend",
                metric="campaign_spend",
                status="available",
                computed_at="2019-01-01T00:00:00Z",
                amount="10",
            ),
            _computed_record(
                evidence_id="estimated-gross",
                metric="gross_value",
                status="estimated",
                computed_at="2026-10-14T10:00:00Z",
                amount="30",
            ),
            _computed_record(
                evidence_id="stale-gross",
                metric="gross_value",
                status="stale",
                computed_at="2026-10-17T10:00:00Z",
                amount="20",
            ),
            _computed_record(
                evidence_id="untimed-gross",
                metric="gross_value",
                status="unknown",
                computed_at=None,
                amount="5",
            ),
        ]
    )
    request = ProjectionRequest(
        projectionId="economic360",
        tenantId="tenant-a",
        subject=ProjectionSubject(kind="campaign", id="campaign-a"),
    )
    registry = ProviderRegistry()
    context = await registry.build_context("economic360", request)

    result = await Economic360Provider(sources=source).project(request, context)

    summary = next(section for section in result.sections if section.id == "summary")
    metrics = summary.content["metrics"]
    spend = metrics["campaign_spend"]
    assert spend["resultStatusCounts"] == {"available": 1}
    assert spend["computedAt"] == {
        "field": "computed_at",
        "timestampCount": 1,
        "timestampCoverage": 1.0,
        "oldest": "2019-01-01T00:00:00Z",
        "latest": "2019-01-01T00:00:00Z",
    }
    # Old age alone does not imply stale without a configured freshness SLA.
    assert spend["freshness"] == {
        "state": "unknown",
        "reason": "freshness_threshold_not_configured",
    }

    gross = metrics["gross_value"]
    assert gross["resultStatusCounts"] == {"estimated": 1, "stale": 1, "unknown": 1}
    assert gross["computedAt"] == {
        "field": "computed_at",
        "timestampCount": 2,
        "timestampCoverage": 0.6667,
        "oldest": "2026-10-14T10:00:00Z",
        "latest": "2026-10-17T10:00:00Z",
    }
    assert gross["freshness"] == {
        "state": "stale",
        "reason": "canonical_result_status_stale",
    }
