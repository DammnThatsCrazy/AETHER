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
    Economic360Provider,
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
    spend_eur = _record(
        "tenant-a", "500", "EUR", metric="campaign_spend", ident="spend-eur"
    )
    revenue = _record(
        "tenant-a", "2500", "USD", usd="2500", metric="gross_value", ident="revenue"
    )
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
async def test_value360_keeps_unbound_ai_cost_scope_unknown(
    monkeypatch, subject_kind: str
) -> None:
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
    monkeypatch.setattr(
        repositories, "get_computation_repository", ExactEmptyComputedRepository
    )
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
