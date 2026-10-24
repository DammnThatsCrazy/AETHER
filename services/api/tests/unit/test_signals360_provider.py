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
    CampaignLinksRead,
    LinkedEntitiesRead,
    LinkedEntity,
    ObservationQualityRead,
    RiskFlagsRead,
    RepositorySignal360Source,
    SignalCampaignLink,
    SignalSummaryRead,
    register_provider,
)
from shared.contracts_models.epistemic import EpistemicStatus  # noqa: E402
from graph.operational_intelligence.models import EvidenceRef  # noqa: E402
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


class FakeLinkedEntitySignalSource(FakeSignalSource):
    def __init__(self, read: LinkedEntitiesRead) -> None:
        super().__init__(SignalSummaryRead((), available=False, complete=False))
        self.link_read = read

    async def linked_entities(
        self, *, tenant_id: str, subject_kind: str, subject_id: str
    ) -> LinkedEntitiesRead:
        return self.link_read


class FakeCampaignLinkSignalSource(FakeSignalSource):
    def __init__(self, read: CampaignLinksRead) -> None:
        super().__init__(SignalSummaryRead((), available=False, complete=False))
        self.campaign_link_read = read
        self.campaign_link_calls: list[tuple[str, str, str]] = []

    async def campaign_links(
        self, *, tenant_id: str, subject_kind: str, subject_id: str
    ) -> CampaignLinksRead:
        self.campaign_link_calls.append((tenant_id, subject_kind, subject_id))
        return self.campaign_link_read


class FakeSignalRepository:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self.row = row
        self.calls: list[tuple[str, str]] = []

    async def get_signal(self, tenant_id: str, signal_id: str) -> dict[str, Any] | None:
        self.calls.append((tenant_id, signal_id))
        return self.row


class FakeIdentityRepository:
    def __init__(
        self,
        *,
        observations: list[dict[str, Any]] | None = None,
        subjects: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.observations = observations or []
        self.subjects = subjects or {}
        self.event_calls: list[tuple[str, list[str], int]] = []
        self.subject_calls: list[tuple[str, str]] = []

    async def get_observations_for_events(
        self, tenant_id: str, event_ids: list[str], limit: int = 500
    ) -> list[dict[str, Any]]:
        self.event_calls.append((tenant_id, event_ids, limit))
        return [
            row
            for row in self.observations
            if row.get("tenant_id") == tenant_id and row.get("source_event_id") in event_ids
        ][:limit]

    async def get_subject_by_canonical_entity_id(
        self, tenant_id: str, entity_id: str
    ) -> dict[str, Any] | None:
        self.subject_calls.append((tenant_id, entity_id))
        row = self.subjects.get(entity_id)
        return row if row is not None and row.get("tenant_id") == tenant_id else None


class FakeCampaignTouchpointRepository:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, str, int]] = []

    async def list_by_source_event(
        self, tenant_id: str, source_event_id: str, *, limit: int
    ) -> list[dict[str, Any]]:
        self.calls.append((tenant_id, source_event_id, limit))
        return [
            row
            for row in self.rows
            if row.get("tenant_id") == tenant_id
            and row.get("source_event_id") == source_event_id
        ][:limit]


class FakeCampaignRepository:
    def __init__(self, rows: dict[str, dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, str]] = []

    async def get_by_id(self, tenant_id: str, campaign_id: Any) -> dict[str, Any] | None:
        campaign_id = str(campaign_id)
        self.calls.append((tenant_id, campaign_id))
        row = self.rows.get(campaign_id)
        return row if row is not None and row.get("tenant_id") == tenant_id else None


def _identity_subject(
    entity_id: str,
    *,
    status: str = "active",
    entity_type: str = "human",
    merged_into_entity_id: str | None = None,
) -> dict[str, Any]:
    return {
        "id": f"identity-row-{entity_id}",
        "tenant_id": TENANT_A,
        "canonical_entity_id": entity_id,
        "entity_type": entity_type,
        "status": status,
        "merged_into_entity_id": merged_into_entity_id,
        "last_seen_at": "2026-10-18T10:00:00Z",
    }


def _identity_observation(
    observation_id: str,
    event_id: str,
    entity_id: str,
    *,
    tenant_id: str = TENANT_A,
) -> dict[str, Any]:
    return {
        "id": observation_id,
        "tenant_id": tenant_id,
        "source_event_id": event_id,
        "canonical_entity_id": entity_id,
        "observed_at": "2026-10-18T10:01:00Z",
        "signal_value_hash": "sensitive-hash-must-not-escape",
        "raw_value_redacted": "sensitive-value-must-not-escape",
    }


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


def _risk_signal(
    signal_id: str,
    *,
    tenant_id: str = TENANT_A,
    subject_kind: str = "event",
    subject_id: str = "event-signals-risk-a",
    evidence_refs: list[dict[str, Any]] | None = None,
    observed_at: str = "2026-10-18T10:01:00Z",
) -> dict[str, Any]:
    return {
        "signal_id": signal_id,
        "tenant_id": tenant_id,
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "risk_dimension": "identity",
        "claim_state": "inferred",
        "confidence": 0.7,
        "evidence_refs": evidence_refs
        if evidence_refs is not None
        else [
            {
                "id": f"evidence-{signal_id}",
                "type": "event",
                "source": "fraud.signals",
                "observedAt": observed_at,
            }
        ],
        "source": "fraud.signals",
        "detector_version": "fraud-v3",
        "observed_at": observed_at,
        "score": 0.61,
    }


class FakeRiskFlagsSource:
    def __init__(self, read: RiskFlagsRead) -> None:
        self.read = read
        self.calls: list[tuple[str, str, str, int]] = []

    async def risk_signals_for_subject(
        self, *, tenant_id: str, subject_kind: str, subject_id: str, limit: int
    ) -> RiskFlagsRead:
        self.calls.append((tenant_id, subject_kind, subject_id, limit))
        return self.read


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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "subject_kind", ["event", "observation", "source", "stream", "signal"]
)
async def test_signals360_projects_exact_subject_risk_signal_records(
    subject_kind: str,
) -> None:
    subject_id = "event-signals-risk-a"
    read = RiskFlagsRead(
        tenant_id=TENANT_A,
        subject_kind=subject_kind,
        subject_id=subject_id,
        records=(
            _risk_signal(
                "risk-signal-exact",
                subject_kind=subject_kind,
                subject_id=subject_id,
            ),
        ),
        available=True,
        complete=True,
    )
    source = FakeRiskFlagsSource(read)
    request = _request(subject_kind=subject_kind, subject_id=subject_id).model_copy(
        update={"includeSections": ["risk_flags"]}
    )

    result = await Signals360Provider(source=source).project(request, _context())

    assert source.calls == [(TENANT_A, subject_kind, subject_id, 100)]
    section = _sections(result)["risk_flags"]
    assert section.state == "degraded"
    assert section.canonicalAuthorityRefs == ["risk_outputs"]
    assert section.content["coverage"] == "exact_tenant_typed_subject_risk_signal_records"
    signal = section.content["signals"][0]
    assert signal["signalId"] == "risk-signal-exact"
    assert signal["subject"] == {"kind": subject_kind, "id": subject_id}
    assert signal["riskDimension"] == "identity"
    assert signal["claimState"] == "inferred"
    assert signal["source"] == "fraud.signals"
    assert signal["detectorVersion"] == "fraud-v3"
    assert signal["observedAt"] == "2026-10-18T10:01:00+00:00"
    assert signal["evidenceRefs"][0]["id"] == "evidence-risk-signal-exact"
    assert signal["evidenceRefs"][0]["source"] == "fraud.signals"
    assert signal["causalAttribution"] == "not_established"
    assert section.content["assessmentState"] == "not_joined"
    assert section.content["producerCoverageState"] == "unknown"
    assert section.content["riskHistoryState"] == "unknown"
    assert section.content["policyState"] == "not_evaluated_by_signals360_risk_read"
    assert section.content["freshnessState"] == "unknown"
    assert section.content["freshnessThresholdSeconds"] is None
    assert section.content["causalAttributionState"] == "not_established"
    assert len(result.claims) == 1
    assert result.claims[0].domainSlotIds == ["risk_flags"]
    assert result.claims[0].claimState == EpistemicStatus.INFERRED
    assert "does not establish event causality" in result.claims[0].claims[0]


@pytest.mark.asyncio
async def test_signals360_empty_risk_read_stays_unknown_not_risk_free() -> None:
    source = FakeRiskFlagsSource(
        RiskFlagsRead(
            tenant_id=TENANT_A,
            subject_kind="event",
            subject_id="event-signals-risk-empty",
            records=(),
            available=True,
            complete=True,
        )
    )
    request = _request(
        subject_kind="event", subject_id="event-signals-risk-empty"
    ).model_copy(update={"includeSections": ["risk_flags"]})

    result = await Signals360Provider(source=source).project(request, _context())

    section = _sections(result)["risk_flags"]
    assert section.state == "unknown"
    assert section.content["signals"] == []
    assert section.content["reasonCode"] == "no_exact_subject_risk_signals_observed"
    assert section.content["producerCoverageState"] == "unknown"
    assert result.claims == []


@pytest.mark.asyncio
async def test_signals360_does_not_read_current_risk_for_historical_request() -> None:
    subject_id = "event-signals-risk-asof"
    source = FakeRiskFlagsSource(
        RiskFlagsRead(
            tenant_id=TENANT_A,
            subject_kind="event",
            subject_id=subject_id,
            records=(_risk_signal("risk-signal-asof", subject_id=subject_id),),
            available=True,
            complete=True,
        )
    )
    request = _request(subject_kind="event", subject_id=subject_id).model_copy(
        update={
            "includeSections": ["risk_flags"],
            "asOf": "2026-10-17T10:00:00Z",
        }
    )

    result = await Signals360Provider(source=source).project(request, _context())

    assert source.calls == []
    section = _sections(result)["risk_flags"]
    assert section.state == "unknown"
    assert section.content["reasonCode"] == "risk_signal_temporal_filter_not_supported"
    assert section.content["signals"] == []


@pytest.mark.asyncio
async def test_signals360_does_not_read_risk_when_slot_is_not_requested() -> None:
    subject_id = "event-signals-risk-not-requested"
    source = FakeRiskFlagsSource(
        RiskFlagsRead(
            tenant_id=TENANT_A,
            subject_kind="event",
            subject_id=subject_id,
            records=(_risk_signal("risk-signal-not-requested", subject_id=subject_id),),
            available=True,
            complete=True,
        )
    )
    request = _request(subject_kind="event", subject_id=subject_id).model_copy(
        update={"includeSections": ["classification"]}
    )

    result = await Signals360Provider(source=source).project(request, _context())

    assert source.calls == []
    section = _sections(result)["risk_flags"]
    assert section.state == "unknown"
    assert section.canonicalAuthorityRefs == []
    assert section.content["signals"] == []


@pytest.mark.asyncio
async def test_signals360_risk_read_rejects_mismatched_tenant_or_subject() -> None:
    subject_id = "event-signals-risk-mismatch"
    source = FakeRiskFlagsSource(
        RiskFlagsRead(
            tenant_id="tenant-signals-other",
            subject_kind="event",
            subject_id=subject_id,
            records=(_risk_signal("risk-signal-mismatch", subject_id=subject_id),),
            available=True,
            complete=True,
        )
    )
    request = _request(subject_kind="event", subject_id=subject_id).model_copy(
        update={"includeSections": ["risk_flags"]}
    )

    result = await Signals360Provider(source=source).project(request, _context())

    section = _sections(result)["risk_flags"]
    assert section.state == "degraded"
    assert section.content["signals"] == []
    assert section.content["authorityReadAvailable"] is False
    assert section.content["reasonCode"] == "risk_signal_read_scope_mismatch"
    assert result.claims == []


@pytest.mark.asyncio
async def test_signals360_risk_read_drops_record_for_different_typed_subject() -> None:
    subject_id = "event-signals-risk-mismatch-record"
    source = FakeRiskFlagsSource(
        RiskFlagsRead(
            tenant_id=TENANT_A,
            subject_kind="event",
            subject_id=subject_id,
            records=(
                _risk_signal(
                    "risk-signal-other-subject",
                    subject_kind="observation",
                    subject_id=subject_id,
                ),
            ),
            available=True,
            complete=True,
        )
    )
    request = _request(subject_kind="event", subject_id=subject_id).model_copy(
        update={"includeSections": ["risk_flags"]}
    )

    result = await Signals360Provider(source=source).project(request, _context())

    section = _sections(result)["risk_flags"]
    assert section.state == "degraded"
    assert section.content["signals"] == []
    assert section.content["reasonCode"] == "risk_signal_rows_invalid_or_missing_evidence"
    assert result.claims == []


@pytest.mark.asyncio
async def test_signals360_risk_read_is_bounded_and_marks_truncation() -> None:
    subject_id = "event-signals-risk-truncated"
    records = tuple(
        _risk_signal(f"risk-signal-{index:03}", subject_id=subject_id)
        for index in range(101)
    )
    source = FakeRiskFlagsSource(
        RiskFlagsRead(
            tenant_id=TENANT_A,
            subject_kind="event",
            subject_id=subject_id,
            records=records,
            available=True,
            complete=True,
        )
    )
    request = _request(subject_kind="event", subject_id=subject_id).model_copy(
        update={"includeSections": ["risk_flags"]}
    )

    result = await Signals360Provider(source=source).project(request, _context())

    section = _sections(result)["risk_flags"]
    assert len(section.content["signals"]) == 100
    assert section.state == "degraded"
    assert section.content["readTruncated"] is True
    assert section.content["authorityReadComplete"] is False


@pytest.mark.asyncio
async def test_repository_signals360_risk_read_is_exact_tenant_and_typed_subject(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject_id = "source-signals-risk-exact"
    matching = _risk_signal(
        "risk-signal-repository-match",
        subject_kind="source",
        subject_id=subject_id,
    )
    repository_calls: list[tuple[str, str, str, int]] = []

    class FakeRiskSignalRepository:
        async def list_by_subject(
            self,
            tenant_id: str,
            subject_kind: str,
            exact_subject_id: str,
            *,
            limit: int,
        ) -> list[dict[str, Any]]:
            repository_calls.append(
                (tenant_id, subject_kind, exact_subject_id, limit)
            )
            return [
                matching,
                _risk_signal(
                    "risk-signal-cross-tenant",
                    tenant_id="tenant-signals-other",
                    subject_kind="source",
                    subject_id=subject_id,
                ),
            ]

    monkeypatch.setattr(
        "intelligence.risk360.store.RiskSignalRepository", FakeRiskSignalRepository
    )

    read = await RepositorySignal360Source().risk_signals_for_subject(
        tenant_id=TENANT_A,
        subject_kind="source",
        subject_id=subject_id,
        limit=100,
    )

    assert repository_calls == [(TENANT_A, "source", subject_id, 101)]
    assert read.records == (matching,)
    assert read.available is True
    assert read.complete is False
    assert read.reason == "risk_signal_subject_scope_mismatch"


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
    assert source_inventory.state == "available"
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
@pytest.mark.parametrize("subject_kind", ["event", "observation"])
async def test_signals360_projects_exact_gateway_accepted_event_classification(
    subject_kind: str,
) -> None:
    event_id = "evt-signals-classification-1"
    record = {
        "tenant_id": TENANT_A,
        "provider_record_id": event_id,
        "source": "sdk",
        "ingested_at": "2026-10-19T10:01:00Z",
        "payload": {
            "event_type": "track",
            "private_property": "must not escape",
            "observation_envelope": {
                "tenancy": {"tenant_id": TENANT_A},
                "observation": {
                    "observation_id": event_id,
                    "observation_type": "track",
                    "family": "core",
                    "schema_version": "observation-envelope/1.0.0",
                    "ingested_at": "2026-10-19T10:00:00Z",
                },
                "quality": {"validation_state": "gateway:accepted"},
            },
        },
    }
    source = FakeSignalSource(
        SignalSummaryRead((), available=False, complete=False),
        ObservationQualityRead(record, available=True, complete=True),
    )
    request = ProjectionRequest(
        projectionId=PROJECTION_ID,
        tenantId=TENANT_A,
        subject=ProjectionSubject(kind=subject_kind, id=event_id),
        includeClaims=True,
        includeSections=["classification"],
    )

    result = await Signals360Provider(source=source).project(request, _context())

    classification = _sections(result)["classification"]
    assert source.quality_calls == [(TENANT_A, event_id)]
    assert classification.state == "available"
    assert classification.canonicalAuthorityRefs == ["events", "observations"]
    assert classification.content["coverage"] == "one_exact_tenant_scoped_sdk_event"
    assert classification.content["classificationState"] == "canonical_event_type_and_family_available"
    assert classification.content["eventType"] == "track"
    assert classification.content["eventFamily"] == "core"
    assert classification.content["classificationBasis"] == "gateway_accepted_canonical_event_registry"
    assert classification.content["sourceClassificationState"] == "unknown"
    assert classification.content["policyState"] == "not_evaluated_by_signals360_classification_read"
    assert classification.content["freshnessState"] == "unknown"
    assert "must not escape" not in str(classification.content)
    assert [ref["source"] for ref in classification.content["evidenceRefs"]] == [
        "bronze_sdk_events",
        "ingestion.ingestion.generated_registry:CANONICAL_EVENT_TYPES/EVENT_FAMILY",
    ]
    claim = next(claim for claim in result.claims if claim.domainSlotIds == ["classification"])
    assert claim.claimState == EpistemicStatus.OBSERVED
    assert {ref.id for ref in claim.evidenceRefs} == {event_id, "track"}


@pytest.mark.asyncio
async def test_signals360_rejects_mismatched_canonical_event_family_classification() -> None:
    event_id = "evt-signals-classification-mismatch"
    record = {
        "tenant_id": TENANT_A,
        "provider_record_id": event_id,
        "source": "sdk",
        "payload": {
            "event_type": "track",
            "observation_envelope": {
                "tenancy": {"tenant_id": TENANT_A},
                "observation": {
                    "observation_id": event_id,
                    "observation_type": "track",
                    "family": "commerce",
                },
                "quality": {"validation_state": "gateway:accepted"},
            }
        },
    }
    source = FakeSignalSource(
        SignalSummaryRead((), available=False, complete=False),
        ObservationQualityRead(record, available=True, complete=True),
    )

    result = await Signals360Provider(source=source).project(
        _request(subject_kind="event", subject_id=event_id), _context()
    )

    classification = _sections(result)["classification"]
    assert classification.state == "unknown"
    assert classification.content["reasonCode"] == "canonical_event_family_mismatch"
    assert "eventType" not in classification.content
    assert classification.content.get("evidenceRefs") is None
    assert not any(claim.domainSlotIds == ["classification"] for claim in result.claims)


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


@pytest.mark.asyncio
async def test_signals360_exact_signal_to_active_canonical_entity_link() -> None:
    signal_id = "MISSING_EXPECTED_ACTION:entity-signals-a:1234"
    signals = FakeSignalRepository(
        {
            **_row(signal_id),
            "entity_id": ENTITY_ID,
            "tenant_id": TENANT_A,
            "signal_id": signal_id,
        }
    )
    identity = FakeIdentityRepository(subjects={ENTITY_ID: _identity_subject(ENTITY_ID)})
    source = RepositorySignal360Source(signals=signals, identity_repository=identity)

    result = await Signals360Provider(source=source).project(
        _request(subject_kind="signal", subject_id=signal_id), _context()
    )

    linked = _sections(result)["linked_entities"]
    assert signals.calls == [(TENANT_A, signal_id)]
    assert identity.subject_calls == [(TENANT_A, ENTITY_ID)]
    assert linked.state == "available"
    assert linked.content["linkedEntities"] == [
        {"id": ENTITY_ID, "entityType": "human", "state": "active"}
    ]
    assert {ref["source"] for ref in linked.content["evidenceRefs"]} == {
        "behavioral_signals",
        "identity_subjects",
    }
    assert len(result.claims) == 1
    assert result.claims[0].domainSlotIds == ["linked_entities"]
    assert result.claims[0].subject == ProjectionSubject(kind="signal", id=signal_id)
    serialized = str(linked.content)
    assert "explanation" not in serialized
    assert "private-event-id" not in serialized
    assert "sensitive-hash" not in serialized


@pytest.mark.asyncio
async def test_signals360_drops_cross_tenant_signal_entity_binding() -> None:
    signal_id = "signal-from-another-tenant"
    signals = FakeSignalRepository(
        {
            **_row(signal_id, tenant_id="tenant-signals-b"),
            "entity_id": "foreign-entity",
            "tenant_id": "tenant-signals-b",
            "signal_id": signal_id,
        }
    )
    identity = FakeIdentityRepository(
        subjects={"foreign-entity": _identity_subject("foreign-entity")}
    )
    source = RepositorySignal360Source(signals=signals, identity_repository=identity)

    result = await Signals360Provider(source=source).project(
        _request(subject_kind="signal", subject_id=signal_id), _context()
    )

    linked = _sections(result)["linked_entities"]
    assert linked.state == "degraded"
    assert linked.content["reasonCode"] == "behavioral_signal_scope_mismatch"
    assert linked.content["linkedEntities"] == []
    assert linked.content["evidenceRefs"] == []
    assert identity.subject_calls == []
    assert result.claims == []


@pytest.mark.asyncio
async def test_signals360_exact_event_identity_join_follows_merge_to_active_subject() -> None:
    event_id = "evt-identity-exact-1"
    identity = FakeIdentityRepository(
        observations=[
            _identity_observation("identity-observation-1", event_id, "entity-old"),
            _identity_observation("identity-observation-2", event_id, "entity-old-2"),
        ],
        subjects={
            "entity-old": _identity_subject(
                "entity-old", status="merged", merged_into_entity_id="entity-current"
            ),
            "entity-old-2": _identity_subject(
                "entity-old-2", status="merged", merged_into_entity_id="entity-current"
            ),
            "entity-current": _identity_subject("entity-current", entity_type="agent"),
        },
    )
    source = RepositorySignal360Source(identity_repository=identity)

    result = await Signals360Provider(source=source).project(
        _request(subject_kind="event", subject_id=event_id), _context()
    )

    linked = _sections(result)["linked_entities"]
    assert identity.event_calls == [(TENANT_A, [event_id], 20)]
    assert linked.state == "available"
    assert linked.content["linkedEntities"] == [
        {"id": "entity-current", "entityType": "agent", "state": "active"}
    ]
    assert {ref["source"] for ref in linked.content["evidenceRefs"]} == {
        "identity_signal_observations",
        "identity_subjects",
    }
    assert {ref["id"] for ref in linked.content["evidenceRefs"]} >= {
        "identity-observation-1",
        "identity-observation-2",
        "entity-old",
        "entity-old-2",
        "entity-current",
    }
    assert "sensitive-hash" not in str(linked.content)
    assert "sensitive-value" not in str(linked.content)
    assert len(result.claims) == 1


@pytest.mark.asyncio
async def test_signals360_observation_does_not_infer_resolver_event_id() -> None:
    identity = FakeIdentityRepository(
        observations=[
            _identity_observation(
                "identity-observation-2", "resolver-event-id", ENTITY_ID
            )
        ],
        subjects={ENTITY_ID: _identity_subject(ENTITY_ID)},
    )
    source = RepositorySignal360Source(identity_repository=identity)
    observation_id = "sdk-observation-id"

    result = await Signals360Provider(source=source).project(
        _request(subject_kind="observation", subject_id=observation_id), _context()
    )

    linked = _sections(result)["linked_entities"]
    assert identity.event_calls == [(TENANT_A, [observation_id], 20)]
    assert linked.state == "unknown"
    assert linked.content["linkedEntities"] == []
    assert linked.content["reasonCode"] == (
        "exact_observation_id_not_bound_to_identity_event_id"
    )
    assert linked.content["evidenceRefs"] == []
    assert result.claims == []


@pytest.mark.asyncio
async def test_signals360_rechecks_link_read_tenant_and_subject_scope() -> None:
    subject = ProjectionSubject(kind="event", id="evt-signals-scope")
    foreign_evidence = EvidenceRef(
        id="foreign-entity",
        type="entity",
        source="identity_subjects",
    )
    source = FakeLinkedEntitySignalSource(
        LinkedEntitiesRead(
            tenant_id="tenant-signals-b",
            subject_kind="event",
            subject_id=subject.id,
            entities=(
                LinkedEntity(
                    entity_id="foreign-entity",
                    entity_type="human",
                    evidence_refs=(foreign_evidence,),
                ),
            ),
            available=True,
            complete=True,
        )
    )

    result = await Signals360Provider(source=source).project(
        _request(subject_kind=subject.kind, subject_id=subject.id), _context()
    )

    linked = _sections(result)["linked_entities"]
    assert linked.state == "degraded"
    assert linked.content["reasonCode"] == "canonical_identity_join_scope_mismatch"
    assert linked.content["linkedEntities"] == []
    assert linked.content["evidenceRefs"] == []
    assert result.claims == []


@pytest.mark.asyncio
async def test_signals360_rejects_conflicting_or_truncated_event_entity_joins() -> None:
    event_id = "evt-identity-conflict"
    conflict_source = RepositorySignal360Source(
        identity_repository=FakeIdentityRepository(
            observations=[
                _identity_observation("identity-observation-a", event_id, "entity-a"),
                _identity_observation("identity-observation-b", event_id, "entity-b"),
            ],
            subjects={
                "entity-a": _identity_subject("entity-a"),
                "entity-b": _identity_subject("entity-b", entity_type="organization"),
            },
        )
    )

    conflict_result = await Signals360Provider(source=conflict_source).project(
        _request(subject_kind="event", subject_id=event_id), _context()
    )
    conflict = _sections(conflict_result)["linked_entities"]
    assert conflict.state == "degraded"
    assert conflict.content["linkedEntities"] == []
    assert conflict.content["reasonCode"] == "identity_event_entity_join_conflicted"
    assert conflict.content["evidenceRefs"] == []
    assert conflict_result.claims == []

    truncated_source = RepositorySignal360Source(
        identity_repository=FakeIdentityRepository(
            observations=[
                _identity_observation(f"identity-observation-{index}", event_id, "entity-a")
                for index in range(20)
            ],
            subjects={"entity-a": _identity_subject("entity-a")},
        )
    )
    truncated_result = await Signals360Provider(source=truncated_source).project(
        _request(subject_kind="event", subject_id=event_id), _context()
    )
    truncated = _sections(truncated_result)["linked_entities"]
    assert truncated.state == "degraded"
    assert truncated.content["linkedEntities"] == []
    assert truncated.content["reasonCode"] == "identity_event_observation_read_truncated"
    assert truncated_result.claims == []


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


@pytest.mark.asyncio
async def test_signals360_campaign_link_requires_exact_event_and_canonical_campaign_scope() -> None:
    from uuid import uuid4

    campaign_id = str(uuid4())
    touchpoint_id = str(uuid4())
    event_id = "evt-signals-campaign-link"
    rows = [
        {
            "tenant_id": TENANT_A,
            "source_event_id": event_id,
            "campaign_id": campaign_id,
            "touchpoint_id": touchpoint_id,
            "occurred_at": "2026-10-20T10:00:00Z",
        },
        {
            "tenant_id": "tenant-signals-b",
            "source_event_id": event_id,
            "campaign_id": str(uuid4()),
            "touchpoint_id": str(uuid4()),
            "occurred_at": "2026-10-20T10:00:00Z",
        },
        {
            "tenant_id": TENANT_A,
            "source_event_id": "another-event",
            "campaign_id": str(uuid4()),
            "touchpoint_id": str(uuid4()),
            "occurred_at": "2026-10-20T10:00:00Z",
        },
    ]

    class UntrustedTouchpointReader:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, int]] = []

        async def list_by_source_event(
            self, tenant_id: str, source_event_id: str, *, limit: int
        ) -> list[dict[str, Any]]:
            self.calls.append((tenant_id, source_event_id, limit))
            return rows

    touchpoints = UntrustedTouchpointReader()
    campaigns = FakeCampaignRepository(
        {
            campaign_id: {
                "tenant_id": TENANT_A,
                "campaign_id": campaign_id,
                "updated_at": "2026-10-20T10:01:00Z",
            }
        }
    )
    source = RepositorySignal360Source(
        campaign_touchpoints=touchpoints,
        campaign_repository=campaigns,
    )

    read = await source.campaign_links(
        tenant_id=TENANT_A,
        subject_kind="event",
        subject_id=event_id,
    )

    assert touchpoints.calls == [(TENANT_A, event_id, 101)]
    assert campaigns.calls == [(TENANT_A, campaign_id)]
    assert read.available is True
    assert read.complete is False
    assert read.reason == "campaign_touchpoint_scope_mismatch"
    assert [link.campaign_id for link in read.links] == [campaign_id]
    assert {
        ref.source
        for ref in read.links[0].evidence_refs
    } == {
        "services/api/journeys/measurement/repositories/"
        "touchpoint_repo.py:silver_campaign_touchpoint_facts",
        "services/api/journeys/measurement/repositories/"
        "touchpoint_repo.py:silver_campaign_touchpoint_facts:source_event_id",
        "services/api/journeys/campaign/repository.py:campaigns",
    }


@pytest.mark.asyncio
async def test_signals360_projects_campaign_links_with_touchpoint_and_campaign_evidence() -> None:
    from uuid import uuid4

    campaign_id = str(uuid4())
    touchpoint_id = str(uuid4())
    refs = (
        EvidenceRef(
            id=touchpoint_id,
            type="event",
            source=(
                "services/api/journeys/measurement/repositories/"
                "touchpoint_repo.py:silver_campaign_touchpoint_facts"
            ),
        ),
        EvidenceRef(
            id="obs-campaign-linked",
            type="event",
            source=(
                "services/api/journeys/measurement/repositories/"
                "touchpoint_repo.py:silver_campaign_touchpoint_facts:source_event_id"
            ),
        ),
        EvidenceRef(
            id=campaign_id,
            type="entity",
            source="services/api/journeys/campaign/repository.py:campaigns",
        ),
    )
    read = CampaignLinksRead(
        tenant_id=TENANT_A,
        subject_kind="observation",
        subject_id="obs-campaign-linked",
        links=(SignalCampaignLink(campaign_id=campaign_id, evidence_refs=refs),),
        available=True,
        complete=True,
    )
    source = FakeCampaignLinkSignalSource(read)

    result = await Signals360Provider(source=source).project(
        _request(subject_kind="observation", subject_id="obs-campaign-linked"),
        _context(),
    )

    section = _sections(result)["campaign_links"]
    assert source.campaign_link_calls == [
        (TENANT_A, "observation", "obs-campaign-linked")
    ]
    assert section.state == "available"
    assert section.content["links"] == [
        {"campaignId": campaign_id, "linkState": "exact_tenant_campaign_touchpoint"}
    ]
    assert section.content["authorityReadComplete"] is True
    assert {item["id"] for item in section.content["evidenceRefs"]} == {
        touchpoint_id,
        "obs-campaign-linked",
        campaign_id,
    }
    assert any(
        claim.domainSlotIds == ["campaign_links"]
        and campaign_id in " ".join(claim.claims)
        for claim in result.claims
    )
