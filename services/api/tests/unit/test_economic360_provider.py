"""Unit tests for the Economic360 intelligence-projection provider (slice S3).

The provider is a read-only, fail-isolated, tenant-scoped projection over
canonical economic truth (ADR-010). These tests cover:

* a valid ``ProjectionResult`` with the registry's typed sections and
  evidence-grounded claims;
* ``extra="forbid"`` conformance (the plane fails closed);
* honest degradation when ``profile360`` / ``relationship360`` / ``outcome360``
  are still ``in_flight`` — recorded in ``dependencyState``, projection still
  returns, never raises;
* degraded results stay content-free when a backing source is unavailable;
* tenant isolation — tenant A never surfaces tenant B's sections/evidence;
* registration via ``register_provider`` (success, duplicate, version
  mismatch, unknown id).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[2]  # .../aether-backend

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from value.economic.economic360_provider import (  # noqa: E402
    OUTPUT_SECTIONS,
    RepositoryAttributionCreditReader,
    Economic360Provider,
    RepositoryConversionInventoryReader,
    RepositoryCampaignIdentityReader,
    RepositoryEconomicSourceReader,
    register_provider,
)
from graph.operational_intelligence.models import EvidenceRef  # noqa: E402
from shared.intelligence_projections import (  # noqa: E402
    ContractVersionIncompatible,
    DuplicateProjection,
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
    ProjectionContext,
    ProjectionNotFound,
    ProjectionRequest,
    ProjectionResult,
    ProjectionSection,
    ProjectionSubject,
    ProviderRegistry,
)


def _request(tenant: str = "tenant-a", **overrides: object) -> ProjectionRequest:
    values: dict[str, object] = {
        "projectionId": "economic360",
        "tenantId": tenant,
        "subject": ProjectionSubject(kind="campaign", id="camp_1"),
    }
    values.update(overrides)
    return ProjectionRequest(**values)


async def _make_context(reg: ProviderRegistry, tenant: str = "tenant-a") -> ProjectionContext:
    """Build a runtime context for an economic360 request (registry truth)."""
    return await reg.build_context("economic360", _request(tenant=tenant))


class FakeSource:
    """Canonical-source test double returning tenant-scoped value records."""

    def __init__(
        self,
        records: list[dict],
        *,
        raises: Exception | None = None,
    ) -> None:
        self._records = records
        self._raises = raises

    async def records(self, *, tenant_id: str, subject: object) -> list[dict]:
        if self._raises is not None:
            raise self._raises
        return list(self._records)

    async def is_canonical_campaign(self, tenant_id: str, campaign_id: str) -> bool:
        # The fake source represents an exact, already-resolved campaign scope.
        return True


class FakeConversionInventory:
    _JOIN_BASIS_BY_SUBJECT_KIND = {
        "profile": "exact_canonical_profile_conversion_id",
        "entity": "exact_canonical_profile_conversion_id",
        "account": "exact_tenant_conversion_account_id",
        "cluster": "exact_canonical_conversion_cluster_id",
        "campaign": "canonical_campaign_touchpoint_or_attribution_conversion_join",
        "journey": "current_tenant_journey_version_conversion_ids",
        "agent": "validated_agent_identity_exact_conversion_agent_id",
    }

    def __init__(
        self,
        *,
        state: str,
        records: list[dict],
        evidence_refs: list[dict],
        reason: str | None = None,
        join_basis: str | None = None,
    ) -> None:
        self.state = state
        self.records = records
        self.evidence_refs = evidence_refs
        self.reason = reason
        self.join_basis = join_basis
        self.calls = 0

    async def read(self, request: ProjectionRequest) -> dict:
        self.calls += 1
        return {
            "tenantId": request.tenantId,
            "subject": request.subject.model_dump(),
            "canonicalAuthority": "canonical_conversions",
            "state": self.state,
            "reason": self.reason,
            "joinBasis": self.join_basis
            or self._JOIN_BASIS_BY_SUBJECT_KIND.get(
                request.subject.kind, "exact_canonical_conversion_id"
            ),
            "completeness": "complete" if self.state == "available" else "partial",
            "records": self.records,
            "evidenceRefs": self.evidence_refs,
            "measurementOutcomeLinkage": {
                "state": "unknown",
                "reason": "outcome360_rows_do_not_expose_canonical_conversion_id",
            },
            "freshness": {
                "state": "unknown",
                "reason": "conversion_freshness_threshold_not_configured",
            },
            "timeScope": {
                "mode": "current_canonical_state",
                "historicalState": "unknown",
            },
            "limitations": ["records_are_canonical_conversion_rows_not_outcome360_measured_outcomes"],
        }


class FakeAttributionCredits:
    def __init__(self, result: dict) -> None:
        self.result = result
        self.calls: list[tuple[str, list[str]]] = []

    async def read(self, tenant_id: str, conversion_ids: list[str]) -> dict:
        self.calls.append((tenant_id, list(conversion_ids)))
        return self.result


def _record(
    tenant: str,
    amount: str,
    currency: str,
    *,
    usd: str | None = None,
    metric: str = "gross_value",
    ident: str = "ev",
) -> dict:
    return {
        "tenant_id": tenant,
        "amount": amount,
        "currency": currency,
        "value_usd": usd,
        "metric_kind": "flow",
        "_source": "test",
        "_evidence_id": ident,
        "_evidence_type": "transaction",
        "_evidence_source": "test/fake",
        "_evidence_uri": f"store://test/{ident}",
        "_metric_name": metric,
    }


@pytest.fixture
def healthy_source() -> FakeSource:
    return FakeSource(
        [
            _record(
                "tenant-a",
                "1000.00",
                "USD",
                usd="1000.00",
                metric="campaign_spend",
                ident="a_spend",
            ),
            _record(
                "tenant-a", "2500.00", "USD", usd="2500.00", metric="gross_value", ident="a_gross"
            ),
        ]
    )


# ---------------------------------------------------------------------------
# Valid result: typed sections + evidence-grounded claims
# ---------------------------------------------------------------------------


async def test_project_returns_valid_result(healthy_source: FakeSource) -> None:
    provider = Economic360Provider(sources=healthy_source)
    request = _request()
    result = await provider.project(request, await _make_context(ProviderRegistry()))

    assert isinstance(result, ProjectionResult)
    assert result.projectionId == "economic360"
    assert result.tenantId == "tenant-a"
    assert result.contractVersion == INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
    assert result.generatedAt  # ISO-8601 UTC
    assert result.degradedReasons == []


async def test_project_emits_exact_registry_sections(healthy_source: FakeSource) -> None:
    provider = Economic360Provider(sources=healthy_source)
    result = await provider.project(_request(), await _make_context(ProviderRegistry()))

    assert [s.id for s in result.sections] == list(OUTPUT_SECTIONS)
    assert OUTPUT_SECTIONS == ("summary", "state", "evidence", "outcomes", "findings")


async def test_section_states_are_typed(healthy_source: FakeSource) -> None:
    provider = Economic360Provider(sources=healthy_source)
    result = await provider.project(_request(), await _make_context(ProviderRegistry()))
    valid_states = {
        "available",
        "degraded",
        "empty",
        "missing",
        "not_applicable",
        "unknown",
    }
    for section in result.sections:
        assert section.state in valid_states, section.id


async def test_claims_are_evidence_grounded(healthy_source: FakeSource) -> None:
    provider = Economic360Provider(sources=healthy_source)
    result = await provider.project(_request(), await _make_context(ProviderRegistry()))

    assert result.claims, "expected evidence-grounded claims"
    for claim in result.claims:
        assert isinstance(claim.subject, ProjectionSubject)
        assert claim.evidenceRefs, f"requiresEvidence: claim {claim.id!r} must carry EvidenceRefs"
        for ref in claim.evidenceRefs:
            assert isinstance(ref, EvidenceRef)
            assert ref.id
    # The spend claim reflects the absorbed campaign_spend metric vocabulary.
    spend_claims = [c for c in result.claims if c.kind == "campaign_spend"]
    assert spend_claims


async def test_economic_claims_route_to_value360_facts_slot(
    healthy_source: FakeSource,
) -> None:
    result = await Economic360Provider(sources=healthy_source).project(
        _request(), await _make_context(ProviderRegistry())
    )

    assert {claim.id for claim in result.claims} >= {
        "summary.total_value_observed",
        "summary.campaign_spend",
    }
    summary_claim = next(
        claim for claim in result.claims if claim.id == "summary.total_value_observed"
    )
    spend_claim = next(claim for claim in result.claims if claim.id == "summary.campaign_spend")
    assert summary_claim.domainSlotIds == [
        "economic_facts_and_state",
        "performance",
        "value_summary",
        "evidence_trace",
    ]
    assert spend_claim.domainSlotIds == ["economic_facts_and_state", "performance"]
    assert summary_claim.evidenceRefs


async def test_economic_campaign_claims_compose_into_campaign_performance_slot(
    healthy_source: FakeSource,
) -> None:
    from shared.intelligence_projections.composition import compose_experience360_frame
    from shared.intelligence_projections.contracts import (
        Experience360FrameRequest,
        Experience360PolicyDisposition,
    )

    subject = ProjectionSubject(kind="campaign", id="camp_1")
    result = await Economic360Provider(sources=healthy_source).project(
        _request(subject=subject), await _make_context(ProviderRegistry())
    )
    frame = compose_experience360_frame(
        Experience360FrameRequest(
            surfaceId="campaign360",
            tenantId="tenant-a",
            subject=subject,
            requestedSlotIds=["performance"],
            includeEvidence=True,
        ),
        [result],
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        generated_at="2026-10-20T12:00:00Z",
    )

    performance_slot = frame.slots[0]
    assert performance_slot.id == "performance"
    assert {claim.kind for claim in performance_slot.claims} >= {
        "economic_rollup",
        "campaign_spend",
    }
    assert {ref.id for ref in performance_slot.evidenceRefs} >= {"a_spend", "a_gross"}


async def test_value_attribution_credit_uses_exact_conversion_and_active_run_evidence() -> None:
    conversion_id = "00000000-0000-4000-8000-000000000101"
    run_id = "00000000-0000-4000-8000-000000000102"
    credit_id = "00000000-0000-4000-8000-000000000103"
    touchpoint_id = "00000000-0000-4000-8000-000000000104"
    touchpoint_source = (
        "services/api/journeys/measurement/repositories/touchpoint_repo.py:"
        "silver_campaign_touchpoint_facts"
    )
    touchpoint_ref = EvidenceRef(
        id=touchpoint_id,
        type="event",
        source=touchpoint_source,
        observedAt="2026-10-19T10:00:00Z",
        uri=f"store://silver_campaign_touchpoint_facts/{touchpoint_id}",
    ).model_dump(mode="json")
    conversion_inventory = FakeConversionInventory(
        state="available",
        records=[{"conversionId": conversion_id}],
        evidence_refs=[
            EvidenceRef(
                id=conversion_id,
                type="transaction",
                source="canonical_conversions",
                uri=f"store://canonical_conversions/{conversion_id}",
                observedAt="2026-10-19T10:00:00Z",
            ).model_dump(mode="json")
        ],
    )
    attribution_reader = FakeAttributionCredits(
        {
            "tenantId": "tenant-a",
            "conversionIds": [conversion_id],
            "state": "available",
            "reason": None,
            "completeness": "complete",
            "runs": [
                {
                    "tenantId": "tenant-a",
                    "conversionId": conversion_id,
                    "attributionRunId": run_id,
                    "modelType": "last_touch",
                    "modelVersion": "v3",
                    "status": "complete",
                    "completedAt": "2026-10-19T10:02:00Z",
                    "modelConfidence": 0.91,
                }
            ],
            "records": [
                {
                    "tenantId": "tenant-a",
                    "conversionId": conversion_id,
                    "attributionRunId": run_id,
                    "creditId": credit_id,
                    "touchpointId": touchpoint_id,
                    "campaignId": "campaign-3",
                    "touchpointJoin": {
                        "state": "resolved",
                        "joinBasis": "exact_tenant_scoped_credit_touchpoint_id",
                    },
                    "canonicalTouchpoint": {
                        "tenantId": "tenant-a",
                        "touchpointId": touchpoint_id,
                        "campaignId": "campaign-3",
                        "occurredAt": "2026-10-19T10:00:00Z",
                        "evidenceRef": touchpoint_ref,
                    },
                    "channel": "web",
                    "source": "newsletter",
                    "sourceClass": "owned",
                    "actorType": "human",
                    "journeyRole": "assist",
                    "attributionEligible": True,
                    "creditWeight": "0.75",
                    "modelConfidence": 0.91,
                    "createdAt": "2026-10-19T10:02:00Z",
                }
            ],
            "freshness": {
                "state": "unknown",
                "reason": "attribution_freshness_threshold_not_configured",
                "completedAtCoverage": 1.0,
                "oldestCompletedAt": "2026-10-19T10:02:00Z",
                "latestCompletedAt": "2026-10-19T10:02:00Z",
            },
            "limitations": [
                "credit_weights_are_canonical_model_outputs_not_independently_measured_value",
                "attributed_revenue_and_agent_roi_are_not_inferred_or_projected",
            ],
        }
    )
    request = _request()
    result = await Economic360Provider(
        sources=FakeSource([]),
        conversion_inventory_reader=conversion_inventory,
        attribution_credit_reader=attribution_reader,
    ).project(request, await _make_context(ProviderRegistry()))

    evidence = next(section for section in result.sections if section.id == "evidence")
    attribution = evidence.content["attribution_credits"]
    assert attribution_reader.calls == [("tenant-a", [conversion_id])]
    assert attribution["state"] == "available"
    assert attribution["freshness"]["state"] == "unknown"
    assert attribution["freshness"]["latestCompletedAt"] == "2026-10-19T10:02:00+00:00"
    assert attribution["records"][0]["creditWeight"] == "0.75"
    assert attribution["records"][0]["touchpointJoin"]["state"] == "resolved"
    assert attribution["records"][0]["canonicalTouchpoint"]["touchpointId"] == touchpoint_id
    assert "attributedGrossRevenue" not in attribution["records"][0]

    claim = next(claim for claim in result.claims if claim.kind == "canonical_attribution_credit")
    assert claim.domainSlotIds == ["attribution_credits", "evidence_trace", "confidence"]
    assert claim.confidence == 0.91
    assert {ref.source for ref in claim.evidenceRefs} == {
        "attribution_runs",
        "attribution_credits",
        "canonical_conversions",
        touchpoint_source,
    }
    assert "model-reported attribution confidence 0.910" in claim.claims[0]
    assert "calibration and applicability to realized value are not independently validated" in claim.claims[0]
    assert "attribution-model output" in claim.claims[0]
    assert "not independently measured realized value or agent ROI" in claim.claims[0]


@pytest.mark.parametrize(
    ("model_confidence", "model_version", "confidence_slot_bound"),
    [(0.84, "v2", True), (None, "v2", False), (0.84, None, False)],
)
def test_value_confidence_slot_requires_score_and_complete_model_lineage(
    model_confidence: float | None,
    model_version: str | None,
    confidence_slot_bound: bool,
) -> None:
    conversion_id = "00000000-0000-4000-8000-000000000301"
    run_id = "00000000-0000-4000-8000-000000000302"
    credit_id = "00000000-0000-4000-8000-000000000303"
    refs = [
        EvidenceRef(
            id=conversion_id,
            type="transaction",
            source="canonical_conversions",
            uri=f"store://canonical_conversions/{conversion_id}",
        ),
        EvidenceRef(
            id=run_id,
            type="model_output",
            source="attribution_runs",
            uri=f"store://attribution_runs/{run_id}",
        ),
        EvidenceRef(
            id=credit_id,
            type="model_output",
            source="attribution_credits",
            uri=f"store://attribution_credits/{credit_id}",
        ),
    ]
    provider = Economic360Provider(sources=FakeSource([]))

    claims = provider._build_claims(
        _request(),
        [],
        {},
        [],
        [],
        attribution_credits={
            "records": [
                {
                    "evidenceRefs": [ref.model_dump(mode="json") for ref in refs],
                    "creditWeight": "0.5",
                    "conversionId": conversion_id,
                    "creditId": credit_id,
                    "attributionRunId": run_id,
                    "modelConfidence": model_confidence,
                    "modelType": "last_touch",
                    "modelVersion": model_version,
                }
            ]
        },
    )

    attribution_claim = next(
        claim for claim in claims if claim.kind == "canonical_attribution_credit"
    )
    assert ("confidence" in attribution_claim.domainSlotIds) is confidence_slot_bound


async def test_value_attribution_credit_does_not_turn_missing_active_run_into_empty() -> None:
    conversion_id = "00000000-0000-4000-8000-000000000201"
    inventory = FakeConversionInventory(
        state="available",
        records=[{"conversionId": conversion_id}],
        evidence_refs=[
            EvidenceRef(
                id=conversion_id,
                type="transaction",
                source="canonical_conversions",
                uri=f"store://canonical_conversions/{conversion_id}",
            ).model_dump(mode="json")
        ],
    )
    reader = FakeAttributionCredits(
        {
            "tenantId": "tenant-a",
            "conversionIds": [conversion_id],
            "state": "unknown",
            "reason": "canonical_active_attribution_run_unavailable",
            "completeness": "unknown",
            "runs": [],
            "records": [],
        }
    )
    result = await Economic360Provider(
        sources=FakeSource([]),
        conversion_inventory_reader=inventory,
        attribution_credit_reader=reader,
    ).project(_request(), await _make_context(ProviderRegistry()))

    evidence = next(section for section in result.sections if section.id == "evidence")
    attribution = evidence.content["attribution_credits"]
    assert attribution["state"] == "unknown"
    assert attribution["reason"] == "canonical_active_attribution_run_unavailable"
    assert attribution["records"] == []
    assert not any(claim.kind == "canonical_attribution_credit" for claim in result.claims)


async def test_value_attribution_credit_discards_cross_tenant_run_and_credit_rows() -> None:
    conversion_id = "00000000-0000-4000-8000-000000000301"
    run_id = "00000000-0000-4000-8000-000000000302"
    credit_id = "00000000-0000-4000-8000-000000000303"
    inventory = FakeConversionInventory(
        state="available",
        records=[{"conversionId": conversion_id}],
        evidence_refs=[
            EvidenceRef(
                id=conversion_id,
                type="transaction",
                source="canonical_conversions",
                uri=f"store://canonical_conversions/{conversion_id}",
            ).model_dump(mode="json")
        ],
    )
    reader = FakeAttributionCredits(
        {
            "tenantId": "tenant-a",
            "conversionIds": [conversion_id],
            "state": "available",
            "completeness": "complete",
            "runs": [
                {
                    "tenantId": "tenant-b",
                    "conversionId": conversion_id,
                    "attributionRunId": run_id,
                    "modelType": "last_touch",
                }
            ],
            "records": [
                {
                    "tenantId": "tenant-b",
                    "conversionId": conversion_id,
                    "attributionRunId": run_id,
                    "creditId": credit_id,
                    "creditWeight": "1",
                }
            ],
        }
    )
    result = await Economic360Provider(
        sources=FakeSource([]),
        conversion_inventory_reader=inventory,
        attribution_credit_reader=reader,
    ).project(_request(), await _make_context(ProviderRegistry()))

    evidence = next(section for section in result.sections if section.id == "evidence")
    attribution = evidence.content["attribution_credits"]
    assert attribution["state"] == "degraded"
    assert attribution["reason"] == "canonical_attribution_credit_scope_or_record_invalid"
    assert attribution["records"] == []
    assert attribution["runs"] == []
    assert not any(claim.kind == "canonical_attribution_credit" for claim in result.claims)


async def test_repository_attribution_reader_uses_tenant_and_exact_conversion(monkeypatch) -> None:
    from journeys.measurement.repositories import attribution_run_repo
    from journeys.measurement.repositories import touchpoint_repo

    tenant_id = "tenant-a"
    conversion_id = "00000000-0000-4000-8000-000000000401"
    run_id = "00000000-0000-4000-8000-000000000402"
    credit_id = "00000000-0000-4000-8000-000000000403"
    touchpoint_id = "00000000-0000-4000-8000-000000000404"
    observed: list[tuple[str, str]] = []

    class ExactRepository:
        async def get_active_run(self, requested_tenant: str, requested_conversion: str):
            observed.append((requested_tenant, requested_conversion))
            return {
                "tenant_id": tenant_id,
                "conversion_id": conversion_id,
                "attribution_run_id": run_id,
                "model_type": "first_touch",
                "model_version": "v2",
                "status": "complete",
                "is_active": True,
                "completed_at": "2026-10-20T09:00:00Z",
                "model_confidence": 0.8,
            }

        async def list_credits_for_run(self, requested_tenant: str, requested_run: str):
            assert (requested_tenant, requested_run) == (tenant_id, run_id)
            return [
                {
                    "tenant_id": tenant_id,
                    "conversion_id": conversion_id,
                    "attribution_run_id": run_id,
                    "credit_id": credit_id,
                    "credit_weight": "1.0",
                    "touchpoint_id": touchpoint_id,
                    "campaign_id": "campaign-7",
                    "created_at": "2026-10-20T09:00:00Z",
                    "source_classifier_version": "source-v4",
                }
            ]

    class ExactTouchpointRepository:
        async def get(self, requested_tenant: str, requested_touchpoint: str):
            assert (requested_tenant, requested_touchpoint) == (tenant_id, touchpoint_id)
            return {
                "tenant_id": tenant_id,
                "touchpoint_id": touchpoint_id,
                "campaign_id": "campaign-7",
                "occurred_at": "2026-10-20T08:55:00Z",
                "received_at": "2026-10-20T08:55:01Z",
            }

    monkeypatch.setattr(attribution_run_repo, "AttributionRunRepository", ExactRepository)
    monkeypatch.setattr(touchpoint_repo, "TouchpointRepository", ExactTouchpointRepository)
    result = await RepositoryAttributionCreditReader().read(tenant_id, [conversion_id])

    assert observed == [(tenant_id, conversion_id)]
    assert result["state"] == "available"
    assert result["canonicalAuthorityRefs"] == [
        "attribution_runs",
        "attribution_credits",
        "campaign_touchpoints",
    ]
    assert result["records"][0]["conversionId"] == conversion_id
    assert result["records"][0]["creditWeight"] == "1.0"
    assert result["records"][0]["touchpointJoin"]["state"] == "resolved"
    assert result["records"][0]["canonicalTouchpoint"]["campaignId"] == "campaign-7"
    assert result["touchpointReadCount"] == 1
    assert result["unresolvedTouchpointCount"] == 0
    assert any(
        ref["source"].endswith(":silver_campaign_touchpoint_facts")
        for ref in result["records"][0]["evidenceRefs"]
    )
    assert result["records"][0]["sourceClassifierVersion"] == "source-v4"
    assert result["freshness"]["state"] == "unknown"


@pytest.mark.parametrize(
    ("touchpoint_mode", "expected_reason"),
    [
        ("missing", "canonical_attribution_touchpoint_join_partial"),
        ("read_error", "canonical_attribution_touchpoint_read_failed"),
        ("foreign_tenant", "canonical_attribution_touchpoint_scope_or_record_invalid"),
        ("campaign_conflict", "canonical_attribution_touchpoint_scope_or_record_invalid"),
    ],
)
async def test_repository_attribution_reader_degrades_unresolved_touchpoint_joins(
    monkeypatch,
    touchpoint_mode: str,
    expected_reason: str,
) -> None:
    from journeys.measurement.repositories import attribution_run_repo
    from journeys.measurement.repositories import touchpoint_repo

    tenant_id = "tenant-a"
    conversion_id = "00000000-0000-4000-8000-000000000411"
    run_id = "00000000-0000-4000-8000-000000000412"
    credit_id = "00000000-0000-4000-8000-000000000413"
    touchpoint_id = "00000000-0000-4000-8000-000000000414"

    class ExactAttributionRepository:
        async def get_active_run(self, requested_tenant: str, requested_conversion: str):
            assert (requested_tenant, requested_conversion) == (tenant_id, conversion_id)
            return {
                "tenant_id": tenant_id,
                "conversion_id": conversion_id,
                "attribution_run_id": run_id,
                "model_type": "first_touch",
                "model_version": "v2",
                "status": "complete",
                "is_active": True,
                "completed_at": "2026-10-20T09:00:00Z",
            }

        async def list_credits_for_run(self, requested_tenant: str, requested_run: str):
            assert (requested_tenant, requested_run) == (tenant_id, run_id)
            return [
                {
                    "tenant_id": tenant_id,
                    "conversion_id": conversion_id,
                    "attribution_run_id": run_id,
                    "credit_id": credit_id,
                    "credit_weight": "0.5",
                    "touchpoint_id": touchpoint_id,
                    "campaign_id": "campaign-7",
                    "created_at": "2026-10-20T09:00:00Z",
                }
            ]

    class TouchpointRepository:
        async def get(self, requested_tenant: str, requested_touchpoint: str):
            assert (requested_tenant, requested_touchpoint) == (tenant_id, touchpoint_id)
            if touchpoint_mode == "missing":
                return None
            if touchpoint_mode == "read_error":
                raise RuntimeError("touchpoint repository unavailable")
            return {
                "tenant_id": "tenant-b" if touchpoint_mode == "foreign_tenant" else tenant_id,
                "touchpoint_id": touchpoint_id,
                "campaign_id": (
                    "campaign-other" if touchpoint_mode == "campaign_conflict" else "campaign-7"
                ),
                "occurred_at": "2026-10-20T08:55:00Z",
                "received_at": "2026-10-20T08:55:01Z",
            }

    monkeypatch.setattr(attribution_run_repo, "AttributionRunRepository", ExactAttributionRepository)
    monkeypatch.setattr(touchpoint_repo, "TouchpointRepository", TouchpointRepository)
    result = await RepositoryAttributionCreditReader().read(tenant_id, [conversion_id])

    assert result["state"] == "degraded"
    assert result["reason"] == expected_reason
    assert result["records"][0]["canonicalTouchpoint"] is None
    assert result["records"][0]["touchpointJoin"]["state"] != "resolved"


async def test_repository_attribution_reader_bounds_touchpoint_lookups(monkeypatch) -> None:
    from journeys.measurement.repositories import attribution_run_repo
    from journeys.measurement.repositories import touchpoint_repo
    from value.economic import economic360_provider as provider_module

    tenant_id = "tenant-a"
    conversion_id = "00000000-0000-4000-8000-000000000421"
    run_id = "00000000-0000-4000-8000-000000000422"
    touchpoint_id = "00000000-0000-4000-8000-000000000423"
    credit_ids = [
        "00000000-0000-4000-8000-000000000424",
        "00000000-0000-4000-8000-000000000425",
    ]
    touchpoint_calls: list[str] = []

    class ExactAttributionRepository:
        async def get_active_run(self, requested_tenant: str, requested_conversion: str):
            return {
                "tenant_id": tenant_id,
                "conversion_id": conversion_id,
                "attribution_run_id": run_id,
                "model_type": "first_touch",
                "model_version": "v2",
                "status": "complete",
                "is_active": True,
                "completed_at": "2026-10-20T09:00:00Z",
            }

        async def list_credits_for_run(self, requested_tenant: str, requested_run: str):
            return [
                {
                    "tenant_id": tenant_id,
                    "conversion_id": conversion_id,
                    "attribution_run_id": run_id,
                    "credit_id": credit_id,
                    "credit_weight": "0.5",
                    "touchpoint_id": touchpoint_id,
                    "campaign_id": "campaign-7",
                    "created_at": "2026-10-20T09:00:00Z",
                }
                for credit_id in credit_ids
            ]

    class TouchpointRepository:
        async def get(self, requested_tenant: str, requested_touchpoint: str):
            touchpoint_calls.append(requested_touchpoint)
            return {
                "tenant_id": tenant_id,
                "touchpoint_id": touchpoint_id,
                "campaign_id": "campaign-7",
                "occurred_at": "2026-10-20T08:55:00Z",
                "received_at": "2026-10-20T08:55:01Z",
            }

    monkeypatch.setattr(provider_module, "_MAX_ATTRIBUTION_TOUCHPOINT_READS", 1)
    monkeypatch.setattr(attribution_run_repo, "AttributionRunRepository", ExactAttributionRepository)
    monkeypatch.setattr(touchpoint_repo, "TouchpointRepository", TouchpointRepository)
    result = await RepositoryAttributionCreditReader().read(tenant_id, [conversion_id])

    assert touchpoint_calls == [touchpoint_id]
    assert result["touchpointReadCount"] == 1
    assert result["touchpointReadTruncated"] is True
    assert result["state"] == "degraded"
    assert result["reason"] == "canonical_attribution_touchpoint_read_truncated"


async def test_summary_surfaces_absorbed_metrics(healthy_source: FakeSource) -> None:
    provider = Economic360Provider(sources=healthy_source)
    result = await provider.project(_request(), await _make_context(ProviderRegistry()))

    summary = next(s for s in result.sections if s.id == "summary")
    metrics = summary.content["metrics"]
    assert metrics["campaign_spend"]["unit"] == "usd"
    assert metrics["campaign_spend"]["usd_value"] == "1000.00"
    assert metrics["gross_value"]["usd_value"] == "2500.00"
    assert metrics["campaign_roas"]["value"] == "2.5000"
    # Not derivable without customer counts — honest absence, never fabricated.
    assert metrics["campaign_cac"]["usd_value"] is None
    assert metrics["campaign_ltv"]["usd_value"] is None


async def test_summary_metric_lineage_points_to_exact_value_and_cost_evidence() -> None:
    spend_usd = _record(
        "tenant-a", "1000", "USD", usd="1000", metric="campaign_spend", ident="spend-usd"
    )
    spend_eur = _record("tenant-a", "500", "EUR", metric="campaign_spend", ident="spend-eur")
    revenue = _record("tenant-a", "2500", "USD", usd="2500", metric="gross_value", ident="revenue")
    ai_cost = _record(
        "tenant-a", "2.50", "USD", usd="2.50", metric="ai_execution_cost", ident="ai-cost"
    )
    ai_cost["_cost_basis"] = "provider_reported"
    provider = Economic360Provider(sources=FakeSource([spend_usd, spend_eur, revenue, ai_cost]))

    result = await provider.project(_request(), await _make_context(ProviderRegistry()))

    summary = next(section for section in result.sections if section.id == "summary")
    metrics = summary.content["metrics"]
    assert summary.content["valueEvidenceRefIds"] == ["spend-usd", "spend-eur", "revenue"]
    assert summary.content["usdContributionEvidenceRefIds"] == ["spend-usd", "revenue"]
    assert metrics["campaign_spend"]["evidenceRefIds"] == ["spend-usd", "spend-eur"]
    assert metrics["campaign_spend"]["usdContributionEvidenceRefIds"] == ["spend-usd"]
    assert metrics["gross_value"]["evidenceRefIds"] == ["revenue"]
    assert metrics["gross_value"]["usdContributionEvidenceRefIds"] == ["revenue"]
    assert metrics["campaign_roas"]["inputEvidenceRefIds"] == {
        "campaign_spend": ["spend-usd"],
        "gross_value": ["revenue"],
    }
    assert metrics["ai_execution_cost"]["evidenceRefIds"] == ["ai-cost"]
    assert metrics["ai_execution_cost"]["usdContributionEvidenceRefIds"] == ["ai-cost"]

    evidence = next(section for section in result.sections if section.id == "evidence")
    assert {ref["id"] for ref in evidence.content["evidence"]} == {
        "spend-usd",
        "spend-eur",
        "revenue",
        "ai-cost",
    }


# ---------------------------------------------------------------------------
# extra="forbid" conformance
# ---------------------------------------------------------------------------


def test_projection_result_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ProjectionResult(
            projectionId="economic360",
            tenantId="tenant-a",
            contractVersion=INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
            sections=[],
            claims=[],
            dependencyState=[],
            generatedAt="2026-08-24T00:00:00Z",
            degradedReasons=[],
            unexpectedField="nope",
        )


def test_section_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ProjectionSection(id="summary", state="available", surprise="x")


async def test_provider_result_conforms_to_extra_forbid(healthy_source: FakeSource) -> None:
    provider = Economic360Provider(sources=healthy_source)
    result = await provider.project(_request(), await _make_context(ProviderRegistry()))
    # Round-trip through the strict contract proves no unexpected fields leak.
    dumped = result.model_dump(mode="json")
    ProjectionResult(**dumped)


# ---------------------------------------------------------------------------
# Missing in_flight dependencies -> recorded + degraded, never raising
# ---------------------------------------------------------------------------


async def test_missing_dependencies_recorded_in_dependency_state(
    healthy_source: FakeSource,
) -> None:
    reg = ProviderRegistry()  # nothing registered -> all siblings "missing"
    context = await _make_context(reg)
    assert {d.projectionId for d in context.dependencyState} == {
        "outcome360",
        "profile360",
        "relationship360",
    }
    assert all(d.state == "missing" for d in context.dependencyState)

    provider = Economic360Provider(sources=healthy_source)
    result = await provider.project(_request(), context)

    # The provider echoes the registry-computed dependency state verbatim.
    assert result.dependencyState == context.dependencyState
    assert {d.projectionId for d in result.dependencyState} == {
        "outcome360",
        "profile360",
        "relationship360",
    }


async def test_outcome_section_degraded_when_outcome360_missing(
    healthy_source: FakeSource,
) -> None:
    provider = Economic360Provider(sources=healthy_source)
    result = await provider.project(_request(), await _make_context(ProviderRegistry()))

    outcomes = next(s for s in result.sections if s.id == "outcomes")
    assert outcomes.state == "degraded"
    assert "not yet implemented" in outcomes.content["reason"]
    # Honest degradation still surfaces what canonical truth provides.
    assert outcomes.content["outcome_value_usd"] == "2500.00"


async def test_dependency_degradation_does_not_raise(healthy_source: FakeSource) -> None:
    provider = Economic360Provider(sources=healthy_source)
    # No registration, no deps available, and yet the projection returns.
    result = await provider.project(_request(), await _make_context(ProviderRegistry()))
    assert result.projectionId == "economic360"
    assert [s.id for s in result.sections] == list(OUTPUT_SECTIONS)


# ---------------------------------------------------------------------------
# Degraded results stay content-free (never crash, never fabricate)
# ---------------------------------------------------------------------------


async def test_unavailable_source_degrades_without_raising() -> None:
    provider = Economic360Provider(
        sources=FakeSource([], raises=RuntimeError("boom: secret-detail"))
    )
    result = await provider.project(_request(), await _make_context(ProviderRegistry()))

    assert result.projectionId == "economic360"
    assert result.degradedReasons == []
    summary = next(s for s in result.sections if s.id == "summary")
    assert summary.state == "missing"
    # No exception message / secret detail leaks into the result.
    assert "secret-detail" not in result.model_dump_json()
    assert "boom" not in result.model_dump_json()


async def test_raising_reader_never_fabricates_a_total() -> None:
    provider = Economic360Provider(sources=FakeSource([], raises=RuntimeError("x")))
    result = await provider.project(_request(), await _make_context(ProviderRegistry()))
    summary = next(s for s in result.sections if s.id == "summary")
    assert summary.content["total_usd"] is None  # not 0, not invented


async def test_repository_ai_costs_are_exactly_bound_to_agent_subject(monkeypatch) -> None:
    from value.economic import ai_aggregation

    observed_filters: dict[str, object] = {}

    async def list_facts(tenant_id: str, *, limit=None, **filters):
        observed_filters.update({"tenant_id": tenant_id, "limit": limit, **filters})
        return [
            {
                "tenant_id": "tenant-a",
                "agent_id": "agent-a",
                "invocation_id": "inv-a",
                "selected_cost": "1.25",
                "currency": "USD",
                "cost_basis": "provider_reported",
                "observed_at": "2026-10-16T08:00:00Z",
                "provenance": {
                    "source": "aether.agent-runtime",
                    "schema_version": "ai.execution.v1",
                    "raw_event_hash": "do-not-expose-this-hash",
                },
            },
            {
                "tenant_id": "tenant-a",
                "agent_id": "agent-b",
                "invocation_id": "inv-b",
                "selected_cost": "90.00",
                "currency": "USD",
            },
            {
                "tenant_id": "tenant-b",
                "agent_id": "agent-a",
                "invocation_id": "inv-c",
                "selected_cost": "900.00",
                "currency": "USD",
            },
            {
                "tenant_id": "tenant-a",
                "agent_id": "agent-a",
                "invocation_id": "inv-unknown",
                "selected_cost": None,
                "currency": "USD",
                "cost_basis": "unknown",
            },
            {
                "tenant_id": "tenant-a",
                "agent_id": "agent-a",
                "invocation_id": "inv-unknown-priced",
                "selected_cost": "77.00",
                "currency": "USD",
                "cost_basis": "unknown",
                "value_usd": "77.00",
            },
            {
                "tenant_id": "tenant-a",
                "agent_id": "agent-a",
                "invocation_id": "inv-eur",
                "selected_cost": "2.00",
                "currency": "EUR",
                "cost_basis": "provider_reported",
            },
        ]

    monkeypatch.setattr(ai_aggregation, "list_facts", list_facts)
    records = await RepositoryEconomicSourceReader()._ai_cost_records(
        "tenant-a", ProjectionSubject(kind="agent", id="agent-a")
    )

    assert observed_filters == {
        "tenant_id": "tenant-a",
        "limit": 501,
        "agent_id": "agent-a",
    }
    assert [record["_evidence_id"] for record in records] == [
        "inv-a",
        "inv-unknown",
        "inv-unknown-priced",
        "inv-eur",
    ]
    assert all(record["_metric_name"] == "agent_execution_cost" for record in records)
    assert records[1]["amount"] is None
    assert records[2]["amount"] is None
    assert records[2]["value_usd"] is None
    assert records[3]["amount"] == "2.00"
    assert records[3]["value_usd"] is None
    assert records[0]["value_usd"] == "1.25"
    assert records[0]["_observed_at"] == "2026-10-16T08:00:00Z"
    assert records[0]["_provenance_source"] == "aether.agent-runtime"
    assert records[0]["_provenance_schema_version"] == "ai.execution.v1"


@pytest.mark.parametrize("subject_kind", ["episode", "journey"])
async def test_repository_ai_cost_reader_reports_unsupported_exact_subject_scope(
    monkeypatch, subject_kind: str
) -> None:
    from value.economic import ai_aggregation

    async def unexpected_read(*args, **kwargs):
        raise AssertionError("unsupported subject must not trigger a broad read")

    monkeypatch.setattr(ai_aggregation, "list_facts", unexpected_read)
    records = await RepositoryEconomicSourceReader()._ai_cost_records(
        "tenant-a", ProjectionSubject(kind=subject_kind, id=f"{subject_kind}-1")
    )
    assert records == [
        {
            "tenant_id": "tenant-a",
            "_source_incomplete_reason": "ai_execution_facts_subject_scope_unavailable",
        }
    ]


@pytest.mark.parametrize("subject_kind", ["episode", "journey"])
async def test_value360_keeps_unbound_ai_cost_scope_unknown(monkeypatch, subject_kind: str) -> None:
    from intelligence.computation import repositories
    from value.economic import ai_aggregation, journey_operation_evidence

    async def unsupported_fact_query(*args, **kwargs):
        raise AssertionError("an unsupported subject must not trigger a broad AI fact read")

    class ExactEmptyComputedRepository:
        async def list_for_subject(
            self, tenant_id: str, subject_type: str, subject_id: str, *, limit: int
        ):
            assert (tenant_id, subject_type, subject_id, limit) == (
                "tenant-a",
                subject_kind,
                f"{subject_kind}-1",
                201,
            )
            return []

    async def no_journey_commerce(tenant_id: str, journey_id: str, *, as_of=None):
        assert (tenant_id, journey_id) == ("tenant-a", "journey-1")
        return {
            "join_basis": "explicit_journey_step_commerce_order_ref",
            "operation_links": [],
            "payment_facts": [],
            "amounts_included": True,
            "operation_link_amounts_included": False,
            "facts_are_aggregated": False,
            "evidence_truncated": False,
        }

    monkeypatch.setattr(ai_aggregation, "list_facts", unsupported_fact_query)
    monkeypatch.setattr(repositories, "get_computation_repository", ExactEmptyComputedRepository)
    monkeypatch.setattr(
        journey_operation_evidence,
        "journey_commerce_operation_evidence",
        no_journey_commerce,
    )
    subject_id = f"{subject_kind}-1"
    result = await Economic360Provider().project(
        _request(subject=ProjectionSubject(kind=subject_kind, id=subject_id)),
        await _make_context(ProviderRegistry()),
    )

    summary = next(section for section in result.sections if section.id == "summary")
    metric = summary.content["metrics"]["ai_execution_cost"]
    assert metric["state"] == "unknown"
    assert metric["usd_value"] is None
    assert metric["subjectBinding"] == {
        "state": "unknown",
        "subject": {"kind": subject_kind, "id": subject_id},
        "reason": "ai_execution_facts_subject_scope_unavailable",
    }
    assert metric["sourceCompleteness"] == "unknown"
    assert "ai_execution_facts_subject_scope_unavailable" in result.degradedReasons
    assert "summary.ai_execution_cost" not in {claim.id for claim in result.claims}


async def test_episode_value360_keeps_unbound_commerce_order_scope_unknown() -> None:
    from shared.intelligence_projections.composition import compose_experience360_frame
    from shared.intelligence_projections.contracts import (
        Experience360FrameRequest,
        Experience360PolicyDisposition,
    )

    subject = ProjectionSubject(kind="episode", id="episode-no-order-link")
    result = await Economic360Provider(sources=FakeSource([])).project(
        _request(subject=subject),
        await _make_context(ProviderRegistry()),
    )

    evidence = next(section for section in result.sections if section.id == "evidence")
    assert evidence.state == "degraded"
    assert evidence.content["operationEvidenceCompleteness"] == "unknown"
    assert evidence.content["economic_operations"] == {
        "episode_id": "episode-no-order-link",
        "join_basis": "unavailable_episode_commerce_order_reference",
        "completeness": "unknown",
        "operation_links": [],
        "payment_facts": [],
        "association_evidence": [],
        "amounts_included": False,
        "facts_are_aggregated": False,
        "unlinked_evidence": "not_inferred",
        "reason": "episode_commerce_order_reference_scope_unavailable",
        "as_of": None,
    }
    assert "episode_commerce_order_reference_scope_unavailable" in result.degradedReasons
    assert not any(claim.id.endswith("commerce_payment") for claim in result.claims)

    frame = compose_experience360_frame(
        Experience360FrameRequest(
            surfaceId="value360",
            tenantId="tenant-a",
            subject=subject,
            requestedSlotIds=["payments_and_commerce_evidence"],
            includeEvidence=True,
        ),
        [result],
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        generated_at="2026-10-18T12:00:00Z",
    )
    payment_slot = frame.slots[0]
    assert payment_slot.id == "payments_and_commerce_evidence"
    assert payment_slot.state == "degraded"
    assert "projection_provider_degraded" in payment_slot.reasonCodes


async def test_agent_cost_is_observable_but_not_positive_business_value() -> None:
    cost = _record(
        "tenant-a",
        "1.25",
        "USD",
        usd="1.25",
        metric="agent_execution_cost",
        ident="inv-agent-a-1",
    )
    cost.update(
        {
            "_cost_basis": "provider_reported",
            "_observed_at": "2026-10-16T08:00:00Z",
            "_provenance_source": "aether.agent-runtime",
            "_provenance_schema_version": "ai.execution.v1",
        }
    )

    class CanonicalAgent:
        async def is_canonical_agent(self, tenant_id: str, agent_id: str):
            assert (tenant_id, agent_id) == ("tenant-a", "agent-a")
            return True

    provider = Economic360Provider(
        sources=FakeSource([cost]), agent_identity_reader=CanonicalAgent()
    )
    request = _request(subject=ProjectionSubject(kind="agent", id="agent-a"))
    result = await provider.project(
        request,
        await _make_context(ProviderRegistry(), tenant="tenant-a"),
    )

    summary = next(section for section in result.sections if section.id == "summary")
    metric = summary.content["metrics"]["ai_execution_cost"]
    assert summary.content["total_usd"] is None
    assert metric["metricName"] == "agent_execution_cost"
    assert metric["usd_value"] == "1.25"
    assert metric["nativeTotalsByCurrency"] == {"USD": "1.25"}
    assert metric["costBasisCounts"] == {"provider_reported": 1}
    assert metric["observedAt"]["latest"] == "2026-10-16T08:00:00Z"
    assert metric["freshness"] == {
        "state": "unknown",
        "reason": "freshness_threshold_not_configured",
    }
    outcomes = next(section for section in result.sections if section.id == "outcomes")
    assert outcomes.content["outcome_value_usd"] is None
    assert "summary.total_value_observed" not in {claim.id for claim in result.claims}
    cost_claim = next(claim for claim in result.claims if claim.id == "summary.ai_execution_cost")
    assert [ref.id for ref in cost_claim.evidenceRefs] == ["inv-agent-a-1"]
    assert cost_claim.evidenceRefs[0].observedAt == "2026-10-16T08:00:00Z"
    assert "not a measured business outcome" in cost_claim.claims[0]
    evidence = next(section for section in result.sections if section.id == "evidence")
    assert evidence.content["sourceProvenance"] == [
        {
            "evidenceId": "inv-agent-a-1",
            "schemaVersion": "ai.execution.v1",
            "source": "aether.agent-runtime",
        }
    ]


async def test_unresolved_agent_identity_keeps_economic_scope_unknown() -> None:
    class UnexpectedSource:
        async def records(self, *, tenant_id: str, subject: object):
            raise AssertionError("identity must be validated before economic reads")

    class UnresolvedAgent:
        async def is_canonical_agent(self, tenant_id: str, agent_id: str):
            return False

    provider = Economic360Provider(
        sources=UnexpectedSource(), agent_identity_reader=UnresolvedAgent()
    )
    result = await provider.project(
        _request(subject=ProjectionSubject(kind="agent", id="unresolved-agent")),
        await _make_context(ProviderRegistry()),
    )

    assert result.degradedReasons == ["agent_canonical_identity_unresolved"]
    assert all(section.state == "unknown" for section in result.sections)
    assert "summary.total_value_observed" not in {claim.id for claim in result.claims}
    assert "summary.ai_execution_cost" not in {claim.id for claim in result.claims}


async def test_journey_commerce_payment_facts_flow_into_economic_evidence_section(
    monkeypatch,
) -> None:
    from value.economic import journey_operation_evidence

    async def exact_journey_evidence(tenant_id: str, journey_id: str, *, as_of=None):
        assert (tenant_id, journey_id) == ("tenant-a", "journey-1")
        return {
            "join_basis": "explicit_journey_step_commerce_order_ref",
            "operation_links": [],
            "payment_facts": [
                {
                    "kind": "payment",
                    "amount": "12.00",
                    "currency": "USD",
                    "amountUsd": "12.00",
                    "lifecycleState": "completed",
                }
            ],
            "amounts_included": True,
            "operation_link_amounts_included": False,
            "facts_are_aggregated": False,
            "evidence_truncated": True,
        }

    monkeypatch.setattr(
        journey_operation_evidence,
        "journey_commerce_operation_evidence",
        exact_journey_evidence,
    )
    provider = Economic360Provider(sources=FakeSource([]))
    result = await provider.project(
        _request(subject=ProjectionSubject(kind="journey", id="journey-1")),
        await _make_context(ProviderRegistry()),
    )

    evidence = next(section for section in result.sections if section.id == "evidence")
    assert evidence.state == "degraded"
    assert evidence.content["operationEvidenceCompleteness"] == "partial"
    assert evidence.content["economic_operations"]["payment_facts"][0]["amount"] == "12.00"
    assert "journey_commerce_evidence_partial" in result.degradedReasons
    summary = next(section for section in result.sections if section.id == "summary")
    outcomes = next(section for section in result.sections if section.id == "outcomes")
    assert summary.content["total_usd"] is None
    assert outcomes.content["outcome_value_usd"] is None
    assert "summary.total_value_observed" not in {claim.id for claim in result.claims}
    assert "summary.ai_execution_cost" not in {claim.id for claim in result.claims}


async def test_campaign_commerce_payment_facts_flow_through_canonical_activity_ref(
    monkeypatch,
) -> None:
    from value.economic import journey_operation_evidence

    async def exact_campaign_evidence(
        tenant_id: str, campaign_id: str, *, as_of: str | None = None
    ):
        assert (tenant_id, campaign_id, as_of) == (
            "tenant-a",
            "campaign-a",
            "2026-10-17T11:00:00Z",
        )
        return {
            "campaign_id": campaign_id,
            "join_basis": "explicit_campaign_scoped_canonical_activity_commerce_order_ref",
            "operation_links": [],
            "payment_facts": [
                {
                    "kind": "payment",
                    "amount": "23.40",
                    "currency": "USD",
                    "amountUsd": "23.40",
                    "joinBasis": "explicit_campaign_scoped_canonical_activity_commerce_order_ref",
                }
            ],
            "association_evidence": [{"activityId": "activity-campaign-payment"}],
            "amounts_included": True,
            "operation_link_amounts_included": False,
            "facts_are_aggregated": False,
            "evidence_truncated": False,
        }

    monkeypatch.setattr(
        journey_operation_evidence,
        "campaign_commerce_operation_evidence",
        exact_campaign_evidence,
    )
    provider = Economic360Provider(sources=FakeSource([]))
    result = await provider.project(
        _request(
            subject=ProjectionSubject(kind="campaign", id="campaign-a"),
            asOf="2026-10-17T11:00:00Z",
            temporalMode="as_of",
        ),
        await _make_context(ProviderRegistry()),
    )

    evidence = next(section for section in result.sections if section.id == "evidence")
    operation = evidence.content["economic_operations"]
    assert operation["payment_facts"][0]["amount"] == "23.40"
    assert operation["association_evidence"][0]["activityId"] == "activity-campaign-payment"
    assert evidence.content["operationEvidenceCompleteness"] == "bounded_read"
    assert "campaign_commerce_evidence_partial" not in result.degradedReasons


async def test_campaign_commerce_payment_claim_routes_to_value360_slot_with_evidence(
    monkeypatch,
) -> None:
    from shared.intelligence_projections.composition import compose_experience360_frame
    from shared.intelligence_projections.contracts import (
        Experience360FrameRequest,
        Experience360PolicyDisposition,
    )
    from value.economic import journey_operation_evidence

    async def exact_campaign_evidence(
        tenant_id: str, campaign_id: str, *, as_of: str | None = None
    ):
        assert (tenant_id, campaign_id) == ("tenant-a", "campaign-a")
        return {
            "campaign_id": campaign_id,
            "join_basis": "explicit_campaign_scoped_canonical_activity_commerce_order_ref",
            "operation_links": [],
            "payment_facts": [
                {
                    "factId": "commerce:order-hash:payment:provider-a:payment-revision:fact-hash",
                    "kind": "payment",
                    "joinBasis": "explicit_campaign_scoped_canonical_activity_commerce_order_ref",
                    "amount": "23.40",
                    "currency": "USD",
                    "lifecycleState": "settled",
                    "reconciliationState": "matched",
                    "evidence": [
                        {
                            "id": "payment-revision",
                            "type": "transaction",
                            "source": "provider-a",
                            "observedAt": "2026-10-17T10:59:00Z",
                        }
                    ],
                }
            ],
            "amounts_included": True,
            "operation_link_amounts_included": False,
            "facts_are_aggregated": False,
            "evidence_truncated": False,
        }

    monkeypatch.setattr(
        journey_operation_evidence,
        "campaign_commerce_operation_evidence",
        exact_campaign_evidence,
    )
    subject = ProjectionSubject(kind="campaign", id="campaign-a")
    result = await Economic360Provider(sources=FakeSource([])).project(
        _request(subject=subject), await _make_context(ProviderRegistry())
    )

    payment_claim = next(claim for claim in result.claims if claim.kind == "commerce_economic_fact")
    assert payment_claim.domainSlotIds == [
        "payments_and_commerce_evidence",
        "performance",
        "evidence_trace",
        "revenue_events",
    ]
    assert [ref.id for ref in payment_claim.evidenceRefs] == ["payment-revision"]
    assert getattr(payment_claim.claimState, "value", payment_claim.claimState) == "observed"
    assert "23.40 USD" in payment_claim.claims[0]
    assert "lifecycle state: settled" in payment_claim.claims[0]
    assert "reconciliation state: matched" in payment_claim.claims[0]
    assert "settled payment event" in payment_claim.claims[0]

    frame = compose_experience360_frame(
        Experience360FrameRequest(
            surfaceId="value360",
            tenantId="tenant-a",
            subject=subject,
            requestedSlotIds=["payments_and_commerce_evidence"],
            includeEvidence=True,
        ),
        [result],
        frame_policy=Experience360PolicyDisposition(state="allowed"),
        generated_at="2026-10-18T12:00:00Z",
    )
    payment_slot = frame.slots[0]
    assert payment_slot.id == "payments_and_commerce_evidence"
    assert [claim.id for claim in payment_slot.claims] == [payment_claim.id]
    assert {ref.id for ref in payment_slot.evidenceRefs} == {"payment-revision"}
    assert payment_slot.freshness.state == "unknown"


async def test_value_reconciliation_exposes_separate_exact_source_observations(
    monkeypatch,
) -> None:
    from value.economic import journey_operation_evidence

    async def exact_journey_evidence(tenant_id: str, journey_id: str, *, as_of=None):
        assert (tenant_id, journey_id) == ("tenant-a", "journey-reconcile")
        return {
            "journey_id": journey_id,
            "join_basis": "explicit_journey_step_commerce_order_ref",
            "completeness": "bounded_read",
            "operation_links": [],
            "payment_facts": [
                {
                    "factId": "commerce:order-hash:payment:stripe:payment-row:eur",
                    "kind": "payment",
                    "commerceOrderRef": "commerce-order-17",
                    "joinBasis": "explicit_journey_step_commerce_order_ref",
                    "provider": "stripe",
                    "sourceRecordId": "provider-payment-22",
                    "evidenceRecordId": "provider-payment-22",
                    "amount": "12.50",
                    "currency": "EUR",
                    "amountUsd": None,
                    "normalizationState": "not_normalized",
                    "lifecycleState": "settled",
                    "reconciliationState": "matched",
                    "evidence": [
                        {
                            "id": "provider-payment-22",
                            "type": "transaction",
                            "source": "stripe",
                        }
                    ],
                },
                {
                    "factId": "commerce:order-hash:settlement:stripe:settlement-row:usd",
                    "kind": "settlement",
                    "commerceOrderRef": "commerce-order-17",
                    "joinBasis": "explicit_journey_step_commerce_order_ref",
                    "provider": "stripe",
                    "sourceRecordId": "provider-settlement-22",
                    "evidenceRecordId": "provider-settlement-22",
                    "amount": "12.50",
                    "currency": "USD",
                    "amountUsd": "12.50",
                    "normalizationState": "native_currency_usd",
                    "lifecycleState": "settled",
                    "reconciliationState": "matched",
                    "settlesPaymentRefs": [
                        {
                            "provider": "stripe",
                            "providerPaymentId": "provider-payment-22",
                        }
                    ],
                    "evidence": [
                        {
                            "id": "provider-settlement-22",
                            "type": "transaction",
                            "source": "stripe",
                        }
                    ],
                },
            ],
            "amounts_included": True,
            "facts_are_aggregated": False,
            "evidence_truncated": False,
        }

    monkeypatch.setattr(
        journey_operation_evidence,
        "journey_commerce_operation_evidence",
        exact_journey_evidence,
    )
    provider = Economic360Provider(
        sources=FakeSource(
            [
                _record(
                    "tenant-a",
                    "10.00",
                    "EUR",
                    usd="11.00",
                    metric="gross_value",
                    ident="economic-value-row-19",
                )
            ]
        )
    )

    async def no_conversion_inventory(request):
        return {}

    async def no_attribution_credits(request, conversion_inventory):
        return {}

    monkeypatch.setattr(provider, "_safe_conversion_inventory", no_conversion_inventory)
    monkeypatch.setattr(provider, "_safe_attribution_credits", no_attribution_credits)
    subject = ProjectionSubject(kind="journey", id="journey-reconcile")
    result = await provider.project(
        _request(subject=subject), await _make_context(ProviderRegistry())
    )

    evidence = next(section for section in result.sections if section.id == "evidence")
    reconciliation = evidence.content["value_reconciliation"]
    assert reconciliation["state"] == "partial"
    assert reconciliation["joinBasis"] == "explicit_journey_step_commerce_order_ref"
    assert [fact["kind"] for fact in reconciliation["commerceFacts"]] == [
        "payment",
        "settlement",
    ]
    eur_payment, usd_settlement = reconciliation["commerceFacts"]
    assert eur_payment["commerceOrderRef"] == "commerce-order-17"
    assert eur_payment["amountUsd"] is None
    assert eur_payment["normalizationState"] == "not_normalized"
    assert usd_settlement["amountUsd"] == "12.50"
    assert usd_settlement["normalizationState"] == "native_currency_usd"
    assert reconciliation["settlementPaymentLinks"] == [
        {
            "settlementFactId": usd_settlement["factId"],
            "paymentFactId": eur_payment["factId"],
            "commerceOrderRef": "commerce-order-17",
            "provider": "stripe",
            "providerPaymentId": "provider-payment-22",
            "providerSettlementId": "provider-settlement-22",
            "state": "source_reference_resolved",
            "basis": "exact_provider_payment_id_and_same_commerce_order_ref",
            "evidenceRefs": eur_payment["evidenceRefs"] + usd_settlement["evidenceRefs"],
        }
    ]
    assert reconciliation["economicRecords"][0]["evidenceRef"]["id"] == (
        "economic-value-row-19"
    )
    assert reconciliation["economicRecords"][0]["amountUsd"] == "11.00"
    assert reconciliation["crossSourceMatch"] == {
        "state": "unavailable",
        "reason": "economic_records_do_not_retain_exact_commerce_order_payment_or_settlement_ids",
    }
    assert "subject_economic_and_commerce_amounts_are_not_compared_or_aggregated" in (
        reconciliation["limitations"]
    )
    assert "settlement_payment_references_do_not_establish_amount_equality_or_finality" in (
        reconciliation["limitations"]
    )
    assert all(
        "amount" not in link and "amountUsd" not in link and "lifecycleState" not in link
        for link in reconciliation["settlementPaymentLinks"]
    )

    reconciliation_claims = [
        claim for claim in result.claims if "reconciliation" in (claim.domainSlotIds or [])
    ]
    assert {claim.kind for claim in reconciliation_claims} == {
        "commerce_value_reconciliation_observation",
        "canonical_settlement_payment_reference",
        "economic_currency_normalization_observation",
    }
    assert len(reconciliation_claims) == 4
    assert all(
        {ref.id for ref in claim.evidenceRefs}
        for claim in reconciliation_claims
    )
    assert all(
        "does not match it to a separate economic record" in claim.claims[0]
        for claim in reconciliation_claims
        if claim.kind == "commerce_value_reconciliation_observation"
    )
    assert all(
        "not reconciled to the commerce observations" in claim.claims[0]
        for claim in reconciliation_claims
        if claim.kind == "economic_currency_normalization_observation"
    )


async def test_value_reconciliation_rejects_commerce_facts_from_wrong_subject(
    monkeypatch,
) -> None:
    from value.economic import journey_operation_evidence

    async def wrong_journey_evidence(tenant_id: str, journey_id: str, *, as_of=None):
        assert (tenant_id, journey_id) == ("tenant-a", "journey-reconcile")
        return {
            "journey_id": "another-journey",
            "join_basis": "explicit_journey_step_commerce_order_ref",
            "payment_facts": [
                {
                    "factId": "commerce:wrong-subject:payment:stripe:payment-row",
                    "kind": "payment",
                    "commerceOrderRef": "commerce-order-other",
                    "joinBasis": "explicit_journey_step_commerce_order_ref",
                    "provider": "stripe",
                    "sourceRecordId": "provider-payment-other",
                    "amount": "999.00",
                    "currency": "USD",
                    "normalizationState": "native_currency_usd",
                    "amountUsd": "999.00",
                    "evidence": [
                        {
                            "id": "wrong-subject-payment",
                            "type": "transaction",
                            "source": "stripe",
                        }
                    ],
                }
            ],
        }

    monkeypatch.setattr(
        journey_operation_evidence,
        "journey_commerce_operation_evidence",
        wrong_journey_evidence,
    )
    provider = Economic360Provider(sources=FakeSource([]))

    async def no_conversion_inventory(request):
        return {}

    async def no_attribution_credits(request, conversion_inventory):
        return {}

    monkeypatch.setattr(provider, "_safe_conversion_inventory", no_conversion_inventory)
    monkeypatch.setattr(provider, "_safe_attribution_credits", no_attribution_credits)
    result = await provider.project(
        _request(subject=ProjectionSubject(kind="journey", id="journey-reconcile")),
        await _make_context(ProviderRegistry()),
    )

    evidence = next(section for section in result.sections if section.id == "evidence")
    reconciliation = evidence.content["value_reconciliation"]
    assert reconciliation["commerceFacts"] == []
    assert not any(
        claim.kind == "commerce_value_reconciliation_observation"
        for claim in result.claims
    )


async def test_entity_value_slot_is_profile_verified_and_direct_scope_only() -> None:
    class CanonicalProfile:
        async def is_canonical_profile(self, tenant_id: str, entity_id: str):
            assert (tenant_id, entity_id) == ("tenant-a", "entity-a")
            return True

    subject = ProjectionSubject(kind="entity", id="entity-a")
    result = await Economic360Provider(
        sources=FakeSource(
            [_record("tenant-a", "19.00", "USD", usd="19.00", ident="entity-value")]
        ),
        profile_identity_reader=CanonicalProfile(),
    ).project(_request(subject=subject), await _make_context(ProviderRegistry()))

    value_claim = next(
        claim for claim in result.claims if claim.id == "summary.total_value_observed"
    )
    assert value_claim.domainSlotIds == [
        "economic_facts_and_state",
        "value_summary",
        "evidence_trace",
        "value",
    ]
    assert [ref.id for ref in value_claim.evidenceRefs] == ["entity-value"]
    assert "entity-scoped" in value_claim.claims[0]
    assert "member or descendant economics" in value_claim.claims[0]


async def test_completed_payment_fact_does_not_claim_value_revenue_event(monkeypatch) -> None:
    from value.economic import journey_operation_evidence

    async def completed_payment(tenant_id: str, journey_id: str, *, as_of=None):
        assert (tenant_id, journey_id) == ("tenant-a", "journey-1")
        return {
            "join_basis": "explicit_journey_step_commerce_order_ref",
            "payment_facts": [
                {
                    "factId": "commerce:order-hash:payment:provider-a:payment-revision:fact-hash",
                    "kind": "payment",
                    "joinBasis": "explicit_journey_step_commerce_order_ref",
                    "amount": "23.40",
                    "currency": "USD",
                    "lifecycleState": "completed",
                    "reconciliationState": "matched",
                    "evidence": [
                        {
                            "id": "payment-revision",
                            "type": "transaction",
                            "source": "provider-a",
                        }
                    ],
                }
            ],
        }

    monkeypatch.setattr(
        journey_operation_evidence,
        "journey_commerce_operation_evidence",
        completed_payment,
    )
    result = await Economic360Provider(sources=FakeSource([])).project(
        _request(subject=ProjectionSubject(kind="journey", id="journey-1")),
        await _make_context(ProviderRegistry()),
    )
    payment_claim = next(claim for claim in result.claims if claim.kind == "commerce_economic_fact")
    assert "evidence_trace" in payment_claim.domainSlotIds
    assert "revenue_events" not in payment_claim.domainSlotIds
    assert "source-recorded settled payment event" not in payment_claim.claims[0]


async def test_entity_commerce_evidence_requires_canonical_profile_before_activity_read(
    monkeypatch,
) -> None:
    from value.economic import journey_operation_evidence

    async def must_not_read(tenant_id: str, entity_id: str, *, as_of=None):
        raise AssertionError("unresolved profile must not read canonical activity")

    class UnresolvedProfile:
        async def is_canonical_profile(self, tenant_id: str, entity_id: str):
            assert (tenant_id, entity_id) == ("tenant-a", "entity-a")
            return False

    monkeypatch.setattr(
        journey_operation_evidence,
        "entity_commerce_operation_evidence",
        must_not_read,
    )
    provider = Economic360Provider(
        sources=FakeSource([]), profile_identity_reader=UnresolvedProfile()
    )
    result = await provider.project(
        _request(subject=ProjectionSubject(kind="entity", id="entity-a")),
        await _make_context(ProviderRegistry()),
    )

    evidence = next(section for section in result.sections if section.id == "evidence")
    operation = evidence.content["economic_operations"]
    assert operation["reason"] == "profile_canonical_identity_unresolved"
    assert operation["payment_facts"] == []
    assert evidence.state == "degraded"
    assert "entity_commerce_evidence_partial" in result.degradedReasons


async def test_entity_commerce_evidence_uses_exact_profile_activity_reference(
    monkeypatch,
) -> None:
    from value.economic import journey_operation_evidence

    async def exact_entity_evidence(tenant_id: str, entity_id: str, *, as_of=None):
        assert (tenant_id, entity_id, as_of) == ("tenant-a", "entity-a", None)
        return {
            "entity_id": entity_id,
            "join_basis": "explicit_canonical_profile_scoped_activity_commerce_order_ref",
            "operation_links": [],
            "payment_facts": [
                {
                    "kind": "payment",
                    "amount": "19.00",
                    "currency": "USD",
                    "amountUsd": "19.00",
                    "joinBasis": "explicit_canonical_profile_scoped_activity_commerce_order_ref",
                }
            ],
            "association_evidence": [{"activityId": "activity-entity-payment"}],
            "amounts_included": True,
            "operation_link_amounts_included": False,
            "facts_are_aggregated": False,
            "evidence_truncated": False,
        }

    class CanonicalProfile:
        async def is_canonical_profile(self, tenant_id: str, entity_id: str):
            return True

    monkeypatch.setattr(
        journey_operation_evidence,
        "entity_commerce_operation_evidence",
        exact_entity_evidence,
    )
    provider = Economic360Provider(
        sources=FakeSource([]), profile_identity_reader=CanonicalProfile()
    )
    result = await provider.project(
        _request(subject=ProjectionSubject(kind="entity", id="entity-a")),
        await _make_context(ProviderRegistry()),
    )

    evidence = next(section for section in result.sections if section.id == "evidence")
    assert evidence.content["economic_operations"]["payment_facts"][0]["amount"] == "19.00"
    assert evidence.content["economic_operations"]["association_evidence"][0]["activityId"] == (
        "activity-entity-payment"
    )
    assert "entity_commerce_evidence_partial" not in result.degradedReasons


async def test_campaign_ai_cost_is_separate_from_campaign_spend_and_outcomes() -> None:
    cost = _record(
        "tenant-a",
        "2.50",
        "USD",
        usd="2.50",
        metric="ai_execution_cost",
        ident="inv-campaign-a-1",
    )
    cost["_cost_basis"] = "billed"
    provider = Economic360Provider(sources=FakeSource([cost]))
    request = _request(subject=ProjectionSubject(kind="campaign", id="camp_1"))
    result = await provider.project(
        request,
        await _make_context(ProviderRegistry(), tenant="tenant-a"),
    )

    summary = next(section for section in result.sections if section.id == "summary")
    metrics = summary.content["metrics"]
    assert summary.content["total_usd"] is None
    assert metrics["campaign_spend"]["usd_value"] is None
    assert metrics["ai_execution_cost"]["usd_value"] == "2.50"
    outcomes = next(section for section in result.sections if section.id == "outcomes")
    assert outcomes.content["outcome_value_usd"] is None


async def test_unresolved_campaign_identity_prevents_economic_source_reads() -> None:
    class UnexpectedSource:
        async def records(self, *, tenant_id: str, subject: object):
            raise AssertionError("campaign identity must be validated before economic reads")

    class UnresolvedCampaign:
        async def is_canonical_campaign(self, tenant_id: str, campaign_id: str):
            return False

    provider = Economic360Provider(
        sources=UnexpectedSource(), campaign_identity_reader=UnresolvedCampaign()
    )
    result = await provider.project(
        _request(subject=ProjectionSubject(kind="campaign", id="external-campaign-1")),
        await _make_context(ProviderRegistry()),
    )

    assert result.degradedReasons == ["campaign_canonical_identity_unresolved"]
    assert result.claims == []
    assert all(section.state == "unknown" for section in result.sections)


async def test_repository_campaign_identity_reader_requires_tenant_canonical_registry_row(
    monkeypatch,
) -> None:
    from journeys.campaign import repository

    canonical_id = "bce92f34-e8bd-4e0f-9910-cfcb19bb35e6"

    class CampaignRepository:
        async def get_by_id(self, tenant_id, campaign_uuid):
            assert str(campaign_uuid) == canonical_id
            return {
                "tenant_id": "tenant-a",
                "campaign_id": campaign_uuid,
            }

    monkeypatch.setattr(repository, "CampaignRegistryRepository", CampaignRepository)
    reader = RepositoryCampaignIdentityReader()

    assert await reader.is_canonical_campaign("tenant-a", canonical_id) is True
    assert await reader.is_canonical_campaign("tenant-b", canonical_id) is False
    assert await reader.is_canonical_campaign("tenant-a", "external-campaign-1") is False


async def test_computed_value_reader_selects_latest_exact_subject_scope(monkeypatch) -> None:
    from intelligence.computation import repositories

    class FakeRepository:
        async def list_for_subject(
            self, tenant_id: str, subject_type: str, subject_id: str, *, limit: int
        ):
            assert (tenant_id, subject_type, subject_id) == ("tenant-a", "campaign", "camp-a")
            assert limit == 201
            rows = [
                {
                    "tenant_id": "tenant-a",
                    "result_id": "old",
                    "definition_id": "campaign.spend",
                    "context_hash": "old-context",
                    "computed_at": "2026-01-01T00:00:00Z",
                    "dimensions": {"subject_type": "campaign", "subject_id": "camp-a"},
                    "value": 5,
                    "currency": "USD",
                },
                {
                    "tenant_id": "tenant-a",
                    "result_id": "latest-spend",
                    "definition_id": "campaign.spend",
                    "context_hash": "latest-context",
                    "computed_at": "2026-02-01T00:00:00Z",
                    "dimensions": {"subject_type": "campaign", "subject_id": "camp-a"},
                    "value": 7,
                    "currency": "USD",
                },
                {
                    "tenant_id": "tenant-a",
                    "result_id": "latest-revenue",
                    "definition_id": "campaign.gross_revenue",
                    "context_hash": "latest-context",
                    "computed_at": "2026-02-01T00:00:00Z",
                    "dimensions": {"subject_type": "campaign", "subject_id": "camp-a"},
                    "value": 11,
                    "currency": "USD",
                },
                {
                    "tenant_id": "tenant-a",
                    "result_id": "other-campaign",
                    "definition_id": "campaign.spend",
                    "context_hash": "foreign-context",
                    "computed_at": "2026-03-01T00:00:00Z",
                    "dimensions": {"subject_type": "campaign", "subject_id": "camp-b"},
                    "value": 999,
                    "currency": "USD",
                },
                {
                    "tenant_id": "tenant-b",
                    "result_id": "other-tenant",
                    "definition_id": "campaign.spend",
                    "context_hash": "foreign-tenant-context",
                    "computed_at": "2026-04-01T00:00:00Z",
                    "dimensions": {"subject_type": "campaign", "subject_id": "camp-a"},
                    "value": 5000,
                    "currency": "USD",
                },
            ]
            return [
                row
                for row in rows
                if row.get("tenant_id") == tenant_id
                and row.get("dimensions", {}).get("subject_type") == subject_type
                and row.get("dimensions", {}).get("subject_id") == subject_id
            ]

    monkeypatch.setattr(repositories, "get_computation_repository", FakeRepository)
    records = await RepositoryEconomicSourceReader()._computed_metric_records(
        "tenant-a", ProjectionSubject(kind="campaign", id="camp-a")
    )

    assert {record["_evidence_id"] for record in records} == {
        "latest-spend",
        "latest-revenue",
    }
    assert {record["amount"] for record in records} == {7, 11}


async def test_computed_journey_reader_uses_exact_tenant_kind_and_id(monkeypatch) -> None:
    from intelligence.computation import repositories

    rows = [
        {
            "tenant_id": "tenant-a",
            "result_id": "journey-latest-gross",
            "definition_id": "campaign.attributed_gross_revenue",
            "definition_version": "1",
            "context_hash": "journey-latest-context",
            "computed_at": "2026-10-17T11:00:00Z",
            "status": "available",
            "dimensions": {"subject_type": "journey", "subject_id": "journey-1"},
            "value": 45,
            "currency": "UNSUPPORTED-CURRENCY",
        },
        {
            "tenant_id": "tenant-a",
            "result_id": "journey-latest-cost",
            "definition_id": "campaign.journey_allocated_cost",
            "definition_version": "1",
            "context_hash": "journey-latest-context",
            "computed_at": "2026-10-17T11:00:00Z",
            "status": "estimated",
            "dimensions": {"subject_type": "journey", "subject_id": "journey-1"},
            "value": 4,
            "currency": "USD",
        },
        {
            "tenant_id": "tenant-a",
            "result_id": "old-journey-result",
            "definition_id": "campaign.attributed_gross_revenue",
            "context_hash": "journey-old-context",
            "computed_at": "2026-10-16T11:00:00Z",
            "dimensions": {"subject_type": "journey", "subject_id": "journey-1"},
            "value": 5,
            "currency": "USD",
        },
        {
            "tenant_id": "tenant-a",
            "result_id": "same-id-other-kind",
            "definition_id": "campaign.attributed_gross_revenue",
            "context_hash": "other-kind-context",
            "computed_at": "2026-10-18T11:00:00Z",
            "dimensions": {"subject_type": "campaign", "subject_id": "journey-1"},
            "value": 900,
            "currency": "USD",
        },
        {
            "tenant_id": "tenant-a",
            "result_id": "other-journey",
            "definition_id": "campaign.attributed_gross_revenue",
            "context_hash": "other-journey-context",
            "computed_at": "2026-10-19T11:00:00Z",
            "dimensions": {"subject_type": "journey", "subject_id": "journey-2"},
            "value": 800,
            "currency": "USD",
        },
        {
            "tenant_id": "tenant-b",
            "result_id": "other-tenant-journey",
            "definition_id": "campaign.attributed_gross_revenue",
            "context_hash": "foreign-context",
            "computed_at": "2026-10-20T11:00:00Z",
            "dimensions": {"subject_type": "journey", "subject_id": "journey-1"},
            "value": 7000,
            "currency": "USD",
        },
    ]

    class FakeRepository:
        async def list_for_subject(
            self, tenant_id: str, subject_type: str, subject_id: str, *, limit: int
        ):
            assert (tenant_id, subject_type, subject_id, limit) == (
                "tenant-a",
                "journey",
                "journey-1",
                201,
            )
            return [
                row
                for row in rows
                if row.get("tenant_id") == tenant_id
                and row.get("dimensions", {}).get("subject_type") == subject_type
                and row.get("dimensions", {}).get("subject_id") == subject_id
            ]

    monkeypatch.setattr(repositories, "get_computation_repository", FakeRepository)
    records = await RepositoryEconomicSourceReader()._computed_metric_records(
        "tenant-a", ProjectionSubject(kind="journey", id="journey-1")
    )

    assert {record["_evidence_id"] for record in records} == {
        "journey-latest-gross",
        "journey-latest-cost",
    }
    by_id = {record["_evidence_id"]: record for record in records}
    assert by_id["journey-latest-gross"]["value_usd"] is None
    assert by_id["journey-latest-gross"]["currency"] == "UNSUPPORTED-CURRENCY"
    assert by_id["journey-latest-cost"]["value_usd"] == "4"
    assert by_id["journey-latest-cost"]["_result_status"] == "estimated"


async def test_journey_value360_economics_keep_unsupported_normalization_unknown(
    monkeypatch,
) -> None:
    from intelligence.computation import repositories
    from value.economic import journey_operation_evidence

    class FakeRepository:
        async def list_for_subject(
            self, tenant_id: str, subject_type: str, subject_id: str, *, limit: int
        ):
            assert (tenant_id, subject_type, subject_id, limit) == (
                "tenant-a",
                "journey",
                "journey-1",
                201,
            )
            return [
                {
                    "tenant_id": "tenant-a",
                    "result_id": "journey-gross-unknown-currency",
                    "definition_id": "campaign.attributed_gross_revenue",
                    "definition_version": "1",
                    "context_hash": "journey-context",
                    "computed_at": "2026-10-17T11:00:00Z",
                    "status": "available",
                    "dimensions": {"subject_type": "journey", "subject_id": "journey-1"},
                    "value": 45,
                    "currency": "UNSUPPORTED-CURRENCY",
                }
            ]

    async def no_commerce_evidence(tenant_id: str, journey_id: str, *, as_of=None):
        assert (tenant_id, journey_id) == ("tenant-a", "journey-1")
        return {
            "join_basis": "explicit_journey_step_commerce_order_ref",
            "operation_links": [],
            "payment_facts": [],
            "amounts_included": True,
            "operation_link_amounts_included": False,
            "facts_are_aggregated": False,
            "evidence_truncated": False,
        }

    monkeypatch.setattr(repositories, "get_computation_repository", FakeRepository)
    monkeypatch.setattr(
        journey_operation_evidence,
        "journey_commerce_operation_evidence",
        no_commerce_evidence,
    )

    provider = Economic360Provider()
    request = _request(subject=ProjectionSubject(kind="journey", id="journey-1"))
    result = await provider.project(request, await _make_context(ProviderRegistry()))

    summary = next(section for section in result.sections if section.id == "summary")
    gross_value = summary.content["metrics"]["gross_value"]
    assert summary.content["subject"] == {"kind": "journey", "id": "journey-1"}
    assert summary.content["total_usd"] is None
    assert summary.content["native_currency"] == "UNSUPPORTED-CURRENCY"
    assert summary.content["native_total"] == "45"
    assert gross_value["usd_value"] is None
    assert gross_value["normalizationState"] == "unknown"
    assert gross_value["nativeTotalsByCurrency"] == {"UNSUPPORTED-CURRENCY": "45"}
    assert gross_value["evidenceRefIds"] == ["journey-gross-unknown-currency"]
    assert gross_value["usdContributionEvidenceRefIds"] == []
    assert "summary.total_value_observed" not in {claim.id for claim in result.claims}

    evidence = next(section for section in result.sections if section.id == "evidence")
    assert evidence.content["evidence"] == [
        {
            "id": "journey-gross-unknown-currency",
            "type": "model_output",
            "source": "services/api/value/economic/computed_results",
            "observedAt": "2026-10-17T11:00:00Z",
            "confidence": None,
            "uri": "store://computed_results/campaign.attributed_gross_revenue",
        }
    ]


async def test_value360_marks_journey_economics_incomplete_without_exact_query(
    monkeypatch,
) -> None:
    from intelligence.computation import repositories
    from value.economic import journey_operation_evidence

    class LegacyRepository:
        async def list_for_tenant(self, tenant_id: str, *, limit: int):
            # This tempting tenant-wide result must never be used as a fallback.
            return [
                {
                    "tenant_id": tenant_id,
                    "result_id": "unscoped-positive-value",
                    "definition_id": "campaign.attributed_gross_revenue",
                    "context_hash": "unscoped-context",
                    "computed_at": "2026-10-17T11:00:00Z",
                    "dimensions": {"subject_type": "journey", "subject_id": "journey-1"},
                    "value": 4500,
                    "currency": "USD",
                }
            ]

    async def no_commerce_evidence(tenant_id: str, journey_id: str, *, as_of=None):
        return {
            "join_basis": "explicit_journey_step_commerce_order_ref",
            "operation_links": [],
            "payment_facts": [],
            "amounts_included": True,
            "operation_link_amounts_included": False,
            "facts_are_aggregated": False,
            "evidence_truncated": False,
        }

    monkeypatch.setattr(repositories, "get_computation_repository", LegacyRepository)
    monkeypatch.setattr(
        journey_operation_evidence,
        "journey_commerce_operation_evidence",
        no_commerce_evidence,
    )
    result = await Economic360Provider().project(
        _request(subject=ProjectionSubject(kind="journey", id="journey-1")),
        await _make_context(ProviderRegistry()),
    )

    summary = next(section for section in result.sections if section.id == "summary")
    gross_value = summary.content["metrics"]["gross_value"]
    assert summary.state == "degraded"
    assert summary.content["sourceCompleteness"] == "partial"
    assert gross_value["usd_value"] is None
    assert "summary.total_value_observed" not in {claim.id for claim in result.claims}
    assert "economic_computed_result_subject_scope_query_unavailable" in result.degradedReasons


# ---------------------------------------------------------------------------
# Tenant isolation — tenant A never surfaces tenant B
# ---------------------------------------------------------------------------


async def test_tenant_a_never_surfaces_tenant_b_economics() -> None:
    source = FakeSource(
        [
            _record(
                "tenant-a",
                "1000.00",
                "USD",
                usd="1000.00",
                metric="campaign_spend",
                ident="a_spend",
            ),
            _record(
                "tenant-a", "2500.00", "USD", usd="2500.00", metric="gross_value", ident="a_gross"
            ),
            _record(
                "tenant-b",
                "999999.00",
                "USD",
                usd="999999.00",
                metric="gross_value",
                ident="b_gross",
            ),
            _record(
                "tenant-b",
                "12345.00",
                "USD",
                usd="12345.00",
                metric="campaign_spend",
                ident="b_spend",
            ),
        ]
    )
    provider = Economic360Provider(sources=source)
    result = await provider.project(
        _request(tenant="tenant-a"), await _make_context(ProviderRegistry(), tenant="tenant-a")
    )

    assert result.tenantId == "tenant-a"
    evidence = next(s for s in result.sections if s.id == "evidence")
    evidence_ids = [e["id"] for e in evidence.content["evidence"]]
    assert all(ident.startswith("a_") for ident in evidence_ids), evidence_ids
    summary = next(s for s in result.sections if s.id == "summary")
    # Total reflects only tenant-a records.
    assert summary.content["total_usd"] == "3500.00"
    # No tenant-b identifier surfaces anywhere in the result.
    serialized = result.model_dump_json()
    assert "tenant-b" not in serialized
    assert "999999" not in serialized


async def test_untagged_economic_records_are_not_assumed_to_belong_to_request_tenant() -> None:
    unscoped_record = _record(
        "tenant-a",
        "7000.00",
        "USD",
        usd="7000.00",
        metric="gross_value",
        ident="unscoped_gross",
    )
    del unscoped_record["tenant_id"]
    source = FakeSource([unscoped_record])
    result = await Economic360Provider(sources=source).project(
        _request(tenant="tenant-a"),
        await _make_context(ProviderRegistry(), tenant="tenant-a"),
    )

    summary = next(section for section in result.sections if section.id == "summary")
    evidence = next(section for section in result.sections if section.id == "evidence")
    assert summary.state == "degraded"
    assert summary.content["total_usd"] is None
    assert evidence.content["evidence"] == []
    assert "economic_source_tenant_scope_mismatch" in result.degradedReasons
    assert result.claims == []
    assert "7000.00" not in result.model_dump_json()


async def test_conversion_inventory_claim_is_exact_and_preserves_native_unknowns() -> None:
    subject = ProjectionSubject(kind="conversion", id="conversion-1")
    evidence_ref = EvidenceRef(
        id="conversion-1",
        type="transaction",
        source="canonical_conversions",
        observedAt="2026-10-20T10:00:00Z",
        uri="store://canonical_conversions/conversion-1",
    )
    inventory = FakeConversionInventory(
        state="available",
        records=[
            {
                "conversionId": "conversion-1",
                "conversionType": "purchase",
                "status": "confirmed",
                "occurredAt": "2026-10-19T09:00:00Z",
                "observedAt": "2026-10-20T10:00:00Z",
                "grossValue": None,
                "netValue": "0",
                "currency": "EUR",
                "normalizedCurrency": "USD",
                "exchangeRate": None,
                "attributionEligible": True,
                "evidenceRefs": [evidence_ref.model_dump(mode="json")],
            }
        ],
        evidence_refs=[evidence_ref.model_dump(mode="json")],
    )
    result = await Economic360Provider(
        sources=FakeSource([]),
        conversion_inventory_reader=inventory,
    ).project(
        _request(subject=subject),
        await _make_context(ProviderRegistry()),
    )

    evidence = next(section for section in result.sections if section.id == "evidence")
    payload = evidence.content["conversion_inventory"]
    claim = next(
        claim for claim in result.claims if claim.kind == "canonical_conversion_inventory"
    )
    assert payload["state"] == "available"
    assert payload["canonicalAuthority"] == "canonical_conversions"
    assert payload["canonicalAuthorityRefs"] == ["canonical_conversions"]
    assert payload["measurementOutcomeLinkage"]["state"] == "unknown"
    assert payload["records"][0]["grossValue"] is None
    assert payload["records"][0]["netValue"] == "0"
    assert payload["records"][0]["currency"] == "EUR"
    assert payload["records"][0]["exchangeRate"] is None
    assert claim.domainSlotIds == ["conversion_inventory", "evidence_trace"]
    assert claim.claimState.value == "observed"
    assert [ref.id for ref in claim.evidenceRefs] == ["conversion-1"]
    assert "not a join to Outcome360" in claim.claims[0]
    assert "0.00" not in claim.claims[0]
    assert "conversion-1" in {ref.id for ref in claim.evidenceRefs}


async def test_value_ltv_uses_exact_confirmed_rows_and_keeps_currency_partitions() -> None:
    subject = ProjectionSubject(kind="profile", id="profile-1")
    rows = []
    refs = []
    for conversion_id, status, amount, currency in [
        ("conversion-usd", "confirmed", "18.50", "USD"),
        ("conversion-eur", "adjusted", "7.25", "EUR"),
        ("conversion-pending", "pending", "100.00", "USD"),
    ]:
        ref = EvidenceRef(
            id=conversion_id,
            type="transaction",
            source="canonical_conversions",
            uri=f"store://canonical_conversions/{conversion_id}",
        )
        refs.append(ref.model_dump(mode="json"))
        rows.append(
            {
                "conversionId": conversion_id,
                "conversionType": "purchase",
                "status": status,
                "occurredAt": "2026-10-19T09:00:00Z",
                "netValue": amount,
                "currency": currency,
                "evidenceRefs": [ref.model_dump(mode="json")],
            }
        )
    inventory = FakeConversionInventory(state="available", records=rows, evidence_refs=refs)
    result = await Economic360Provider(
        sources=FakeSource([]), conversion_inventory_reader=inventory
    ).project(
        _request(
            subject=subject,
            timeRange={"from": "2026-10-01T00:00:00Z", "to": "2026-11-01T00:00:00Z"},
        ),
        await _make_context(ProviderRegistry()),
    )

    evidence = next(section for section in result.sections if section.id == "evidence")
    ltv = evidence.content["ltv"]
    claim = next(claim for claim in result.claims if claim.kind == "ltv_evidence")
    assert ltv["tenantId"] == "tenant-a"
    assert ltv["subject"] == subject.model_dump()
    assert ltv["canonicalAuthorityRefs"] == ["canonical_conversions"]
    assert ltv["state"] == "degraded"
    assert ltv["amount"] is None
    assert ltv["currency"] is None
    assert ltv["amountBasis"] is None
    assert ltv["observedNetValueByCurrency"] == {"EUR": "7.25", "USD": "18.50"}
    assert ltv["reason"] == "canonical_ltv_lifecycle_coverage_not_proven"
    assert ltv["sourceCompleteness"] == "complete"
    assert ltv["completeness"] == "partial"
    assert ltv["eligibleConversionCount"] == 2
    assert ltv["excludedNonFinalCount"] == 1
    assert ltv["coverage"] == {
        "knownNetValueCount": 2,
        "eligibleConversionCount": 2,
        "ratio": 1.0,
    }
    assert ltv["timeScope"]["mode"] == "explicit_occurred_at_window"
    assert ltv["timeScope"]["fromExclusive"] == "2026-10-01T00:00:00Z"
    assert ltv["timeScope"]["toExclusive"] == "2026-11-01T00:00:00Z"
    assert ltv["timeScope"]["lifetimeCompleteness"] == "unknown"
    assert {ref.id for ref in claim.evidenceRefs} == {"conversion-usd", "conversion-eur"}
    assert claim.domainSlotIds == ["ltv", "evidence_trace"]
    assert "not reported as complete lifetime value" in claim.claims[1]
    assert "not an LTV amount" in claim.claims[0]


async def test_value_ltv_does_not_emit_partial_total_when_a_final_row_has_no_net_value() -> None:
    subject = ProjectionSubject(kind="profile", id="profile-2")
    evidence_refs = []
    records = []
    for conversion_id, net_value in [("known-net", "12.00"), ("unknown-net", None)]:
        ref = EvidenceRef(
            id=conversion_id,
            type="transaction",
            source="canonical_conversions",
            uri=f"store://canonical_conversions/{conversion_id}",
        )
        evidence_refs.append(ref.model_dump(mode="json"))
        records.append(
            {
                "conversionId": conversion_id,
                "status": "confirmed",
                "occurredAt": "2026-10-19T09:00:00Z",
                "netValue": net_value,
                "currency": "USD",
                "evidenceRefs": [ref.model_dump(mode="json")],
            }
        )
    inventory = FakeConversionInventory(
        state="available", records=records, evidence_refs=evidence_refs
    )
    result = await Economic360Provider(
        sources=FakeSource([]), conversion_inventory_reader=inventory
    ).project(
        _request(subject=subject),
        await _make_context(ProviderRegistry()),
    )

    evidence = next(section for section in result.sections if section.id == "evidence")
    ltv = evidence.content["ltv"]
    assert evidence.state == "degraded"
    assert ltv["state"] == "degraded"
    assert ltv["amount"] is None
    assert ltv["currency"] is None
    assert ltv["observedNetValueByCurrency"] == {"USD": "12.00"}
    assert ltv["missingNetValueCount"] == 1
    assert ltv["coverage"] == {
        "knownNetValueCount": 1,
        "eligibleConversionCount": 2,
        "ratio": 0.5,
    }
    assert "canonical_ltv_conversion_coverage_partial" in evidence.warnings


async def test_value_ltv_empty_inventory_preserves_absence_as_unknown_amount_not_zero() -> None:
    subject = ProjectionSubject(kind="profile", id="profile-3")
    inventory = FakeConversionInventory(state="empty", records=[], evidence_refs=[])
    result = await Economic360Provider(
        sources=FakeSource([]), conversion_inventory_reader=inventory
    ).project(
        _request(subject=subject),
        await _make_context(ProviderRegistry()),
    )

    evidence = next(section for section in result.sections if section.id == "evidence")
    ltv = evidence.content["ltv"]
    assert ltv["state"] == "empty"
    assert ltv["amount"] is None
    assert ltv["currency"] is None
    assert ltv["observedNetValueByCurrency"] == {}
    assert ltv["reason"] == "no_canonical_conversion_rows_for_exact_subject"
    assert not any(claim.kind == "ltv_evidence" for claim in result.claims)


async def test_value_ltv_missing_inventory_stays_missing_with_no_evidence_claim() -> None:
    subject = ProjectionSubject(kind="profile", id="profile-missing")
    inventory = FakeConversionInventory(state="missing", records=[], evidence_refs=[])
    result = await Economic360Provider(
        sources=FakeSource([]), conversion_inventory_reader=inventory
    ).project(
        _request(subject=subject),
        await _make_context(ProviderRegistry()),
    )

    evidence = next(section for section in result.sections if section.id == "evidence")
    ltv = evidence.content["ltv"]
    assert ltv["state"] == "missing"
    assert ltv["amount"] is None
    assert ltv["observedNetValueByCurrency"] == {}
    assert ltv["evidenceRefs"] == []
    assert not any(claim.kind == "ltv_evidence" for claim in result.claims)


async def test_value_ltv_keeps_bounded_inventory_partial_and_suppresses_scalar() -> None:
    subject = ProjectionSubject(kind="profile", id="profile-bounded")
    ref = EvidenceRef(
        id="conversion-first-page",
        type="transaction",
        source="canonical_conversions",
        uri="store://canonical_conversions/conversion-first-page",
    )
    inventory = FakeConversionInventory(
        state="degraded",
        records=[
            {
                "conversionId": "conversion-first-page",
                "status": "confirmed",
                "occurredAt": "2026-10-19T09:00:00Z",
                "netValue": "21.00",
                "currency": "USD",
                "evidenceRefs": [ref.model_dump(mode="json")],
            }
        ],
        evidence_refs=[ref.model_dump(mode="json")],
        reason="canonical_conversion_inventory_truncated",
    )
    result = await Economic360Provider(
        sources=FakeSource([]), conversion_inventory_reader=inventory
    ).project(
        _request(subject=subject),
        await _make_context(ProviderRegistry()),
    )

    evidence = next(section for section in result.sections if section.id == "evidence")
    ltv = evidence.content["ltv"]
    claim = next(claim for claim in result.claims if claim.kind == "ltv_evidence")
    assert ltv["state"] == "degraded"
    assert ltv["reason"] == "canonical_conversion_inventory_truncated"
    assert ltv["sourceCompleteness"] == "partial"
    assert ltv["completeness"] == "partial"
    assert ltv["amount"] is None
    assert ltv["observedNetValueByCurrency"] == {"USD": "21.00"}
    assert [evidence_ref["id"] for evidence_ref in ltv["evidenceRefs"]] == [
        "conversion-first-page"
    ]
    assert "known net-value coverage is 1/1" in claim.claims[0]
    assert "completeness is partial" in claim.claims[0]


async def test_value_ltv_rejects_a_noncanonical_subject_join_basis() -> None:
    subject = ProjectionSubject(kind="profile", id="profile-wrong-join")
    ref = EvidenceRef(
        id="conversion-wrong-join",
        type="transaction",
        source="canonical_conversions",
        uri="store://canonical_conversions/conversion-wrong-join",
    )
    inventory = FakeConversionInventory(
        state="available",
        records=[
            {
                "conversionId": "conversion-wrong-join",
                "status": "confirmed",
                "occurredAt": "2026-10-19T09:00:00Z",
                "netValue": "9.00",
                "currency": "USD",
                "evidenceRefs": [ref.model_dump(mode="json")],
            }
        ],
        evidence_refs=[ref.model_dump(mode="json")],
        join_basis="exact_canonical_conversion_id",
    )
    result = await Economic360Provider(
        sources=FakeSource([]), conversion_inventory_reader=inventory
    ).project(
        _request(subject=subject),
        await _make_context(ProviderRegistry()),
    )

    evidence = next(section for section in result.sections if section.id == "evidence")
    ltv = evidence.content["ltv"]
    assert ltv["state"] == "unknown"
    assert ltv["reason"] == "canonical_conversion_subject_join_unverified_for_ltv"
    assert ltv["evidenceRefs"] == []
    assert ltv["observedNetValueByCurrency"] == {}
    assert not any(claim.kind == "ltv_evidence" for claim in result.claims)


async def test_conversion_inventory_rejects_evidence_outside_canonical_conversion_authority() -> None:
    subject = ProjectionSubject(kind="profile", id="profile-evidence-gate")
    foreign_ref = EvidenceRef(
        id="conversion-1",
        type="transaction",
        source="untrusted_source",
        observedAt="2026-10-20T10:00:00Z",
        uri="https://example.test/conversion-1",
    )
    inventory = FakeConversionInventory(
        state="available",
        records=[{"conversionId": "conversion-1", "netValue": "10.00"}],
        evidence_refs=[foreign_ref.model_dump(mode="json")],
    )
    result = await Economic360Provider(
        sources=FakeSource([]),
        conversion_inventory_reader=inventory,
    ).project(
        _request(subject=subject),
        await _make_context(ProviderRegistry()),
    )

    evidence = next(section for section in result.sections if section.id == "evidence")
    payload = evidence.content["conversion_inventory"]
    assert payload["state"] == "degraded"
    assert payload["reason"] == "canonical_conversion_inventory_evidence_missing"
    assert payload["records"] == []
    assert payload["evidenceRefs"] == []
    assert not any(claim.kind == "canonical_conversion_inventory" for claim in result.claims)
    ltv = evidence.content["ltv"]
    assert ltv["state"] == "degraded"
    assert ltv["amount"] is None
    assert ltv["observedNetValueByCurrency"] == {}
    assert ltv["evidenceRefs"] == []
    assert not any(claim.kind == "ltv_evidence" for claim in result.claims)


async def test_conversion_inventory_as_of_request_fails_closed_before_reader() -> None:
    inventory = FakeConversionInventory(state="available", records=[], evidence_refs=[])
    subject = ProjectionSubject(kind="conversion", id="conversion-1")
    result = await Economic360Provider(
        sources=FakeSource([]),
        conversion_inventory_reader=inventory,
    ).project(
        _request(subject=subject, asOf="2026-10-19T00:00:00Z"),
        await _make_context(ProviderRegistry()),
    )

    evidence = next(section for section in result.sections if section.id == "evidence")
    payload = evidence.content["conversion_inventory"]
    assert inventory.calls == 0
    assert payload["state"] == "unknown"
    assert payload["reason"] == "canonical_conversion_history_not_bitemporal"
    assert not any(claim.kind == "canonical_conversion_inventory" for claim in result.claims)


async def test_repository_conversion_inventory_uses_journey_recorded_conversion_ids(
    monkeypatch,
) -> None:
    from journeys.measurement.repositories import conversion_repo, journey_repo

    class ExactJourneyRepository:
        async def get_current(self, tenant_id: str, journey_id: str):
            assert (tenant_id, journey_id) == ("tenant-a", "journey-1")
            return {
                "tenant_id": "tenant-a",
                "journey_id": "journey-1",
                "journey_version_id": "journey-version-1",
                "is_current": True,
                "conversion_ids": '["conversion-1", "missing-conversion"]',
            }

    class ExactConversionRepository:
        def __init__(self):
            self.lookups = []

        async def get(self, tenant_id: str, conversion_id: str):
            self.lookups.append((tenant_id, conversion_id))
            if conversion_id == "missing-conversion":
                return None
            return {
                "tenant_id": "tenant-a",
                "conversion_id": "conversion-1",
                "conversion_type": "purchase",
                "conversion_status": "confirmed",
                "occurred_at": "2026-10-19T09:00:00Z",
                "observed_at": "2026-10-20T10:00:00Z",
                "gross_value": "10.00",
                "net_value": None,
                "currency": "USD",
                "normalized_currency": "USD",
                "attribution_eligible": True,
            }

    conversion_repository = ExactConversionRepository()
    monkeypatch.setattr(journey_repo, "JourneyRepository", ExactJourneyRepository)
    monkeypatch.setattr(
        conversion_repo,
        "ConversionRepository",
        lambda: conversion_repository,
    )

    request = _request(subject=ProjectionSubject(kind="journey", id="journey-1"))
    result = await RepositoryConversionInventoryReader().read(request)

    assert conversion_repository.lookups == [
        ("tenant-a", "conversion-1"),
        ("tenant-a", "missing-conversion"),
    ]
    assert result["state"] == "degraded"
    assert result["reason"] == "canonical_conversion_references_unresolved"
    assert result["joinBasis"] == "current_tenant_journey_version_conversion_ids"
    assert [record["conversionId"] for record in result["records"]] == ["conversion-1"]
    assert result["records"][0]["netValue"] is None
    assert [ref["id"] for ref in result["evidenceRefs"]] == ["conversion-1"]
    assert result["measurementOutcomeLinkage"]["state"] == "unknown"


@pytest.mark.parametrize(
    ("subject_kind", "expected_join_basis"),
    [
        ("conversion", "exact_canonical_conversion_id"),
        ("profile", "exact_canonical_profile_conversion_id"),
        ("entity", "exact_canonical_profile_conversion_id"),
        ("cluster", "exact_canonical_conversion_cluster_id"),
        ("campaign", "canonical_campaign_touchpoint_or_attribution_conversion_join"),
        ("account", "exact_tenant_conversion_account_id"),
        ("agent", "validated_agent_identity_exact_conversion_agent_id"),
    ],
)
async def test_repository_conversion_inventory_uses_exact_supported_subject_joins(
    monkeypatch,
    subject_kind: str,
    expected_join_basis: str,
) -> None:
    from journeys.measurement.repositories import conversion_repo

    subject_id = "conversion-1" if subject_kind == "conversion" else "subject-1"
    row = {
        "tenant_id": "tenant-a",
        "conversion_id": "conversion-1",
        "conversion_type": "purchase",
        "conversion_status": "confirmed",
        "occurred_at": "2026-10-19T09:00:00Z",
        "observed_at": "2026-10-20T10:00:00Z",
        "gross_value": "10.00",
        "currency": "USD",
    }
    identity_column = {
        "profile": "profile_id",
        "entity": "profile_id",
        "cluster": "cluster_id",
        "account": "account_id",
        "agent": "agent_id",
    }.get(subject_kind)
    if identity_column:
        row[identity_column] = subject_id

    class ExactIdentityReader:
        async def is_canonical_profile(self, tenant_id: str, identity_id: str):
            assert (tenant_id, identity_id) == ("tenant-a", subject_id)
            return True

        async def is_canonical_campaign(self, tenant_id: str, identity_id: str):
            assert (tenant_id, identity_id) == ("tenant-a", subject_id)
            return True

        async def is_canonical_agent(self, tenant_id: str, identity_id: str):
            assert (tenant_id, identity_id) == ("tenant-a", subject_id)
            return True

    class ExactConversionRepository:
        calls: list[tuple[str, tuple, dict]] = []

        async def get(self, tenant_id: str, conversion_id: str):
            self.calls.append(("get", (tenant_id, conversion_id), {}))
            return row

        async def list_by_profile(self, tenant_id: str, identity_id: str, **kwargs):
            self.calls.append(("profile", (tenant_id, identity_id), kwargs))
            return [row]

        async def list_by_campaign(self, tenant_id: str, campaign_id: str, **kwargs):
            self.calls.append(("campaign", (tenant_id, campaign_id), kwargs))
            return [row]

        async def list_by_tenant(self, tenant_id: str, **kwargs):
            self.calls.append(("tenant", (tenant_id,), kwargs))
            return [row]

        async def list_by_account(self, tenant_id: str, account_id: str, **kwargs):
            self.calls.append(("account", (tenant_id, account_id), kwargs))
            return [row]

        async def list_by_agent(self, tenant_id: str, agent_id: str, **kwargs):
            self.calls.append(("agent", (tenant_id, agent_id), kwargs))
            return [row]

    repository = ExactConversionRepository()
    monkeypatch.setattr(conversion_repo, "ConversionRepository", lambda: repository)
    identities = ExactIdentityReader()
    result = await RepositoryConversionInventoryReader(
        agent_identity_reader=identities,
        campaign_identity_reader=identities,
        profile_identity_reader=identities,
    ).read(
        _request(subject=ProjectionSubject(kind=subject_kind, id=subject_id))
    )

    if subject_kind in {"account", "cluster"}:
        assert result["state"] == "degraded"
        assert result["completeness"] == "partial"
    else:
        assert result["state"] == "available"
        assert result["completeness"] == "complete"
    assert result["joinBasis"] == expected_join_basis
    assert [record["conversionId"] for record in result["records"]] == ["conversion-1"]
    assert [ref["id"] for ref in result["evidenceRefs"]] == ["conversion-1"]
    assert all(call[1][0] == "tenant-a" for call in repository.calls)
    if subject_kind in {"profile", "entity"}:
        assert repository.calls[0][2]["identity_type"] == "profile"
    elif subject_kind == "cluster":
        assert repository.calls[0][2]["identity_type"] == "cluster"
    elif subject_kind == "campaign":
        assert repository.calls[0][2]["include_unattributed"] is True
    elif subject_kind in {"account", "agent"}:
        assert repository.calls[0][0] == subject_kind
        assert row[f"{subject_kind}_id"] == subject_id
        assert repository.calls[0][2]["limit"] == 501
    if subject_kind == "agent":
        roster = result["agentRoster"]
        assert roster["identityState"] == "validated"
        assert roster["completeness"] == "unknown"
        assert roster["freshness"]["state"] == "unknown"


@pytest.mark.parametrize("subject_kind", ["account", "cluster"])
async def test_unvalidated_or_bounded_conversion_subject_empties_remain_unknown(
    monkeypatch,
    subject_kind: str,
) -> None:
    from journeys.measurement.repositories import conversion_repo

    class ExactIdentityReader:
        async def is_canonical_agent(self, tenant_id: str, agent_id: str):
            return True

    class EmptyConversionRepository:
        async def list_by_profile(self, tenant_id: str, identity_id: str, **kwargs):
            return []

        async def list_by_tenant(self, tenant_id: str, **kwargs):
            return []

        async def list_by_account(self, tenant_id: str, account_id: str, **kwargs):
            return []

    monkeypatch.setattr(
        conversion_repo,
        "ConversionRepository",
        EmptyConversionRepository,
    )
    identity_reader = ExactIdentityReader()
    result = await RepositoryConversionInventoryReader(
        agent_identity_reader=identity_reader,
    ).read(
        _request(subject=ProjectionSubject(kind=subject_kind, id="subject-1"))
    )

    assert result["state"] == "unknown"
    assert result["completeness"] == "unknown"
    assert result["records"] == []
    assert result["evidenceRefs"] == []


async def test_exact_agent_conversion_empty_is_complete_but_roster_is_unknown(monkeypatch) -> None:
    from journeys.measurement.repositories import conversion_repo

    class ExactIdentityReader:
        async def is_canonical_agent(self, tenant_id: str, agent_id: str):
            return True

    class EmptyConversionRepository:
        async def list_by_agent(self, tenant_id: str, agent_id: str, **kwargs):
            assert (tenant_id, agent_id) == ("tenant-a", "agent-1")
            return []

    monkeypatch.setattr(conversion_repo, "ConversionRepository", EmptyConversionRepository)
    result = await RepositoryConversionInventoryReader(
        agent_identity_reader=ExactIdentityReader(),
    ).read(
        _request(subject=ProjectionSubject(kind="agent", id="agent-1"))
    )

    assert result["state"] == "empty"
    assert result["completeness"] == "complete"
    assert result["agentRoster"]["identityState"] == "validated"
    assert result["agentRoster"]["completeness"] == "unknown"
    assert result["agentRoster"]["freshness"]["state"] == "unknown"


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_register_provider_succeeds_on_fresh_registry() -> None:
    reg = ProviderRegistry()
    register_provider(reg)
    assert "economic360" in reg.sources()
    assert reg.sources()["economic360"] == "services/api/value/economic"
    provider = reg.require("economic360")
    assert isinstance(provider, Economic360Provider)


def test_register_duplicate_different_object_raises() -> None:
    reg = ProviderRegistry()
    register_provider(reg)
    with pytest.raises(DuplicateProjection) as excinfo:
        register_provider(reg)
    assert excinfo.value.projection_id == "economic360"


def test_register_version_mismatch_raises() -> None:
    class _WrongVersion:
        projection_id = "economic360"
        contract_version = "2.0.0"

        async def project(self, request: object, context: object) -> object:
            return None

    reg = ProviderRegistry()
    with pytest.raises(ContractVersionIncompatible):
        reg.register(_WrongVersion())


def test_register_unknown_id_raises() -> None:
    class _UnknownId:
        projection_id = "no_such_projection"
        contract_version = "1.0.0"

        async def project(self, request: object, context: object) -> object:
            return None

    reg = ProviderRegistry()
    with pytest.raises(ProjectionNotFound) as excinfo:
        reg.register(_UnknownId())
    assert excinfo.value.projection_id == "no_such_projection"


def test_provider_contract_version_matches_registry() -> None:
    assert Economic360Provider.contract_version == INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION
    # The default reader is the repository-backed one (no injection).
    assert isinstance(Economic360Provider()._sources, RepositoryEconomicSourceReader)
