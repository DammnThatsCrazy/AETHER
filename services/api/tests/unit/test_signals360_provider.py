"""Focused contract tests for the native Signals360 projection provider."""

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
os.environ.setdefault("JWT_SECRET", "signals360-test-secret")

from intelligence.signals.signals360_provider import (  # noqa: E402
    OUTPUT_SECTIONS,
    PROJECTION_ID,
    Signals360Provider,
    ObservationQualityRead,
    RepositorySignal360Source,
    SignalSummaryRead,
    register_provider,
)
from shared.contracts_models.epistemic import EpistemicStatus  # noqa: E402
from shared.intelligence_projections.contracts import (  # noqa: E402
    ProjectionContext,
    ProjectionRequest,
    ProjectionSubject,
)
from shared.intelligence_projections.registry import ProviderRegistry  # noqa: E402

TENANT_A = "tenant-signals-a"
ENTITY_ID = "entity-signals-a"


class FakeSignalSource:
    def __init__(
        self,
        read: SignalSummaryRead,
        observation_quality_read: ObservationQualityRead | None = None,
    ) -> None:
        self.read = read
        self.observation_quality_read = observation_quality_read
        self.calls: list[tuple[str, str, int]] = []
        self.quality_calls: list[tuple[str, str]] = []

    async def entity_signals(
        self, *, tenant_id: str, entity_id: str, limit: int
    ) -> SignalSummaryRead:
        self.calls.append((tenant_id, entity_id, limit))
        return self.read

    async def observation_quality(
        self, *, tenant_id: str, observation_id: str
    ) -> ObservationQualityRead:
        self.quality_calls.append((tenant_id, observation_id))
        return self.observation_quality_read or ObservationQualityRead(
            None, True, True, "exact_sdk_observation_not_found"
        )


def _row(
    signal_id: str,
    *,
    tenant_id: str = TENANT_A,
    entity_id: str = ENTITY_ID,
    severity: str = "high",
    sentiment: str = "caution",
    confidence: float = 0.83,
) -> dict[str, Any]:
    return {
        "signal_id": signal_id,
        "tenant_id": tenant_id,
        "entity_id": entity_id,
        "signal_type": "MISSING_EXPECTED_ACTION",
        "family": "continuity",
        "severity": severity,
        "sentiment": sentiment,
        "confidence": confidence,
        "last_detected": "2026-10-18T10:00:00Z",
        "created_at": "2026-10-18T10:01:00Z",
        "is_stale": False,
        "projection_source": "behavior_profile_translator",
        # These are deliberately excluded: translator refs may be metrics or
        # event IDs, and the explanation may contain sensitive derived data.
        "evidence_refs": ["gold_asset_composition", "private-event-id"],
        "explanation": "private explanation with profile details",
    }


def _request(*, subject_kind: str = "entity", subject_id: str = ENTITY_ID) -> ProjectionRequest:
    return ProjectionRequest(
        projectionId=PROJECTION_ID,
        tenantId=TENANT_A,
        subject=ProjectionSubject(kind=subject_kind, id=subject_id),
        includeClaims=True,
        includeSections=list(OUTPUT_SECTIONS),
    )


def _context() -> ProjectionContext:
    return ProjectionContext(
        projectionId=PROJECTION_ID,
        tenantId=TENANT_A,
        registryState="implemented",
        dependencyState=[],
        warnings=[],
    )


def _sections(result) -> dict[str, Any]:
    return {section.id: section for section in result.sections}


def test_signals360_registers_through_provider_registry() -> None:
    registry = ProviderRegistry()

    register_provider(registry)

    assert registry.get(PROJECTION_ID) is not None


@pytest.mark.asyncio
async def test_signals360_projects_only_tenant_scoped_translator_records() -> None:
    source = FakeSignalSource(
        SignalSummaryRead(
            rows=(
                _row("AT_RISK_OF_CHURN:entity-a:1"),
                _row(
                    "DISCOUNT_SENSITIVE:entity-a:2",
                    severity="medium",
                    sentiment="caution",
                    confidence=0.71,
                ),
            ),
            available=True,
            complete=True,
        )
    )

    result = await Signals360Provider(source=source).project(_request(), _context())

    assert result.projectionId == "signals360"
    assert result.tenantId == TENANT_A
    assert [section.id for section in result.sections] == list(OUTPUT_SECTIONS)
    assert source.calls == [(TENANT_A, ENTITY_ID, 100)]
    sections = _sections(result)

    summary = sections["signal_summary"]
    assert summary.state == "available"
    assert summary.content["signalKind"] == "translator_derived_behavioral_signal"
    assert summary.content["signalCount"] == 2
    assert summary.content["countsBySeverity"] == {"high": 1, "medium": 1}
    assert summary.content["countsBySentiment"] == {"caution": 2}
    assert "explanation" not in str(summary.content)
    assert "private-event-id" not in str(summary.content)
    assert "gold_asset_composition" not in str(summary.content)
    assert {ref["source"] for ref in summary.content["evidenceRefs"]} == {"behavioral_signals"}
    assert {ref["type"] for ref in summary.content["evidenceRefs"]} == {"model_output"}

    assert len(result.claims) == 2
    assert all(claim.domainSlotIds == ["signal_summary"] for claim in result.claims)
    assert all(claim.claimState == EpistemicStatus.OBSERVED for claim in result.claims)

    unsupported = {
        "source_inventory",
        "classification",
        "quality",
        "normalization",
        "linked_entities",
        "campaign_links",
        "risk_flags",
    }
    assert all(sections[slot_id].state == "unknown" for slot_id in unsupported)
    assert all(sections[slot_id].content["reasonCode"] for slot_id in unsupported)
    assert sections["freshness"].state == "degraded"
    assert sections["freshness"].content["sourceFreshnessState"] == "unknown"
    assert sections["freshness"].content["freshnessThresholdSeconds"] is None
    assert sections["evidence_trace"].state == "degraded"
    assert sections["evidence_trace"].content["sourceEventEvidenceState"] == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize("subject_kind", ["event", "observation"])
async def test_signals360_projects_only_gateway_quality_for_exact_observation(
    subject_kind: str,
) -> None:
    observation_id = "evt-signals-exact-1"
    record = {
        "tenant_id": TENANT_A,
        "provider_record_id": observation_id,
        "source": "sdk",
        "payload": {
            "event_type": "page_view",
            "observation_envelope": {
                "tenancy": {"tenant_id": TENANT_A},
                "observation": {
                    "observation_id": observation_id,
                    "observation_type": "page_view",
                    "family": "web",
                    "schema_version": "observation-envelope/1.0.0",
                    "ingested_at": "2026-10-18T10:01:00Z",
                },
                "source": {
                    "source_type": "sdk",
                    "source_relationship": "first_party_application",
                    "ingress_path": "/v1/batch",
                },
                "provenance": {"adapter": "sdk", "adapter_version": "1.0.0"},
                "quality": {"validation_state": "gateway:accepted"},
                "payload": {"private": "must not escape"},
            },
        },
    }
    source = FakeSignalSource(
        SignalSummaryRead((), available=False, complete=False),
        ObservationQualityRead(record, available=True, complete=True),
    )

    result = await Signals360Provider(source=source).project(
        _request(subject_kind=subject_kind, subject_id=observation_id), _context()
    )

    assert source.calls == []
    assert source.quality_calls == [(TENANT_A, observation_id)]
    sections = _sections(result)
    quality = sections["quality"]
    assert quality.state == "degraded"
    assert quality.canonicalAuthorityRefs == ["observations"]
    assert quality.content["coverage"] == "one_exact_sdk_observation"
    assert quality.content["qualityState"] == "gateway_validation_only"
    assert quality.content["validationState"] == "gateway:accepted"
    assert quality.content["sourceReliability"] == "unknown"
    assert quality.content["eventSemanticQuality"] == "unknown"
    assert "must not escape" not in str(quality.content)
    assert quality.content["evidenceRefs"][0]["id"] == observation_id
    assert quality.content["evidenceRefs"][0]["source"] == "bronze_sdk_events"
    source_inventory = sections["source_inventory"]
    assert source_inventory.state == "degraded"
    assert source_inventory.content["coverage"] == "one_exact_sdk_observation"
    source_item = source_inventory.content["sources"][0]
    assert source_item["observationId"] == observation_id
    assert source_item["sourceType"] == "sdk"
    assert source_item["sourceRelationship"] == "first_party_application"
    assert source_item["ingressPath"] == "/v1/batch"
    assert source_item["adapter"] == "sdk"
    assert source_item["adapterVersion"] == "1.0.0"
    assert source_item["observedAt"] == "2026-10-18T10:01:00+00:00"
    assert source_item["evidenceRefs"][0]["id"] == observation_id
    assert len(result.claims) == 2
    assert {claim.domainSlotIds[0] for claim in result.claims} == {
        "quality",
        "source_inventory",
    }
    assert all(claim.claimState == EpistemicStatus.OBSERVED for claim in result.claims)
    assert all(claim.evidenceRefs[0].id == observation_id for claim in result.claims)


@pytest.mark.asyncio
async def test_signals360_quality_rejects_cross_tenant_bronze_evidence() -> None:
    observation_id = "evt-signals-private"
    source = FakeSignalSource(
        SignalSummaryRead((), available=False, complete=False),
        ObservationQualityRead(
            {
                "tenant_id": "tenant-signals-b",
                "provider_record_id": observation_id,
                "source": "sdk",
                "payload": {
                    "observation_envelope": {
                        "tenancy": {"tenant_id": "tenant-signals-b"},
                        "observation": {"observation_id": observation_id},
                        "quality": {"validation_state": "gateway:accepted"},
                    }
                },
            },
            available=True,
            complete=True,
        ),
    )

    result = await Signals360Provider(source=source).project(
        _request(subject_kind="event", subject_id=observation_id), _context()
    )

    quality = _sections(result)["quality"]
    assert quality.state == "unknown"
    assert quality.content["reasonCode"] == "sdk_observation_scope_mismatch"
    assert "evidenceRefs" not in quality.content
    assert result.claims == []


class FakeBronzeRepository:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[dict[str, Any]] = []

    async def find_many(self, *, filters: dict[str, str], limit: int) -> list[dict[str, Any]]:
        self.calls.append({"filters": filters, "limit": limit})
        return [
            row for row in self.rows if all(row.get(key) == value for key, value in filters.items())
        ][:limit]


@pytest.mark.asyncio
async def test_repository_signals360_source_reads_only_exact_tenant_event_bronze_row() -> None:
    observation_id = "evt-signals-exact-repository"
    bronze = FakeBronzeRepository(
        [
            {
                "tenant_id": TENANT_A,
                "provider_record_id": observation_id,
                "source": "sdk",
                "payload": {
                    "observation_envelope": {
                        "tenancy": {"tenant_id": TENANT_A},
                        "observation": {"observation_id": observation_id},
                        "quality": {"validation_state": "gateway:accepted"},
                    }
                },
            },
            {
                "tenant_id": "tenant-signals-b",
                "provider_record_id": observation_id,
                "source": "sdk",
                "payload": {},
            },
        ]
    )

    read = await RepositorySignal360Source(bronze=bronze).observation_quality(
        tenant_id=TENANT_A,
        observation_id=observation_id,
    )

    assert bronze.calls == [
        {
            "filters": {
                "tenant_id": TENANT_A,
                "provider_record_id": observation_id,
            },
            "limit": 2,
        }
    ]
    assert read.available is True
    assert read.complete is True
    assert read.record["tenant_id"] == TENANT_A


@pytest.mark.asyncio
async def test_signals360_reports_empty_only_for_a_complete_exact_entity_read() -> None:
    source = FakeSignalSource(SignalSummaryRead((), available=True, complete=True))

    result = await Signals360Provider(source=source).project(_request(), _context())

    sections = _sections(result)
    assert sections["signal_summary"].state == "empty"
    assert sections["signal_summary"].content["signalCount"] == 0
    assert sections["signal_summary"].content["signals"] == []
    assert result.claims == []
    assert sections["freshness"].state == "unknown"
    assert sections["evidence_trace"].state == "unknown"


@pytest.mark.asyncio
async def test_signals360_does_not_turn_cross_tenant_rows_into_a_zero_summary() -> None:
    source = FakeSignalSource(
        SignalSummaryRead(
            rows=(_row("private-signal", tenant_id="tenant-signals-b"),),
            available=True,
            complete=True,
        )
    )

    result = await Signals360Provider(source=source).project(_request(), _context())

    summary = _sections(result)["signal_summary"]
    assert summary.state == "degraded"
    assert summary.content["signals"] == []
    assert "signalCount" not in summary.content
    assert summary.content["reasonCode"] == "unscoped_or_invalid_signal_rows_dropped"
    assert result.claims == []


@pytest.mark.asyncio
async def test_signals360_keeps_unsupported_subjects_unknown_without_querying_signal_store() -> (
    None
):
    source = FakeSignalSource(SignalSummaryRead((), available=True, complete=True))

    result = await Signals360Provider(source=source).project(
        _request(subject_kind="source", subject_id="provider:crm"),
        _context(),
    )

    assert source.calls == []
    sections = _sections(result)
    assert sections["signal_summary"].state == "unknown"
    assert sections["signal_summary"].content["reasonCode"] == (
        "subject_kind_not_supported_by_signal_repository"
    )


@pytest.mark.asyncio
async def test_signals360_degrades_repository_failures_without_asserting_zero() -> None:
    source = FakeSignalSource(
        SignalSummaryRead(
            (),
            available=False,
            complete=False,
            reason="behavioral_signal_repository_unavailable",
        )
    )

    result = await Signals360Provider(source=source).project(_request(), _context())

    summary = _sections(result)["signal_summary"]
    assert summary.state == "degraded"
    assert summary.content["signals"] == []
    assert "signalCount" not in summary.content
    assert summary.content["reasonCode"] == "behavioral_signal_repository_unavailable"
    assert result.claims == []


@pytest.mark.asyncio
async def test_signals360_rejects_mismatched_projection_tenant_context() -> None:
    source = FakeSignalSource(SignalSummaryRead((), available=True, complete=True))
    context = _context().model_copy(update={"tenantId": "tenant-signals-b"})

    with pytest.raises(ValueError, match="scope must match"):
        await Signals360Provider(source=source).project(_request(), context)

    assert source.calls == []
