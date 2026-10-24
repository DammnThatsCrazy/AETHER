"""Focused Commerce360 provider tests over exact commerce-order references."""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from graph.operational_intelligence.models import EvidenceRef  # noqa: E402
from shared.intelligence_projections import (  # noqa: E402
    INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION,
    ProjectionContext,
    ProjectionRequest,
    ProjectionSubject,
    ProviderRegistry,
)
from shared.intelligence_projections.generated_registry import (  # noqa: E402
    INTELLIGENCE_PROJECTION_DEFINITIONS,
)
from value.commerce.commerce360_provider import (  # noqa: E402
    OUTPUT_SECTIONS,
    Commerce360Provider,
    RepositoryCommerceProductOfferCatalogEvidenceSource,
    register_provider,
)
from value.commerce.product_offer_catalog import (  # noqa: E402
    CommerceOfferRecord,
    CommerceProductOfferCatalogRepository,
    CommerceProductRecord,
)

TENANT = "tenant-a"
SUBJECT_ID = "campaign-1"
JOIN_BASIS = "explicit_campaign_scoped_canonical_activity_commerce_order_ref"


class FakeCommerceSource:
    def __init__(self, result: Optional[dict[str, Any]] = None, *, fail: bool = False) -> None:
        self.result = result
        self.fail = fail
        self.calls: list[tuple[str, str, str, Optional[str]]] = []

    async def read(self, tenant_id, subject, *, as_of):
        self.calls.append((tenant_id, subject.kind, subject.id, as_of))
        if self.fail:
            raise RuntimeError("sensitive storage failure detail")
        if self.result is None:
            return _empty_source(tenant_id, subject.kind, subject.id)
        return self.result


def _request(
    *,
    subject_kind: str = "campaign",
    subject_id: str = SUBJECT_ID,
    tenant_id: str = TENANT,
    **overrides: Any,
) -> ProjectionRequest:
    values: dict[str, Any] = {
        "projectionId": "commerce360",
        "tenantId": tenant_id,
        "subject": ProjectionSubject(kind=subject_kind, id=subject_id),
        "asOf": "2026-10-20T12:00:00+00:00",
    }
    values.update(overrides)
    return ProjectionRequest(**values)


def _context(request: ProjectionRequest, *, tenant_id: Optional[str] = None) -> ProjectionContext:
    return ProjectionContext(
        projectionId="commerce360",
        tenantId=tenant_id or request.tenantId,
        registryState="implemented",
        dependencyState=[],
        asOf=request.asOf,
        warnings=[],
    )


def _evidence(ref_id: str, kind: str = "transaction") -> dict[str, Any]:
    return EvidenceRef(
        id=ref_id,
        type=kind,
        source="stripe",
        observedAt="2026-10-20T11:59:00+00:00",
    ).model_dump(mode="json")


def _fact(
    fact_id: str = "commerce:abc:payment:stripe:pay-1:hash",
    *,
    order_ref: str = "order-ref-1",
    join_basis: str = JOIN_BASIS,
    evidence: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    return {
        "factId": fact_id,
        "kind": "payment",
        "commerceOrderRef": order_ref,
        "joinBasis": join_basis,
        "amount": "25.00",
        "currency": "USD",
        "amountUsd": "25.00",
        "normalizationState": "native_currency_usd",
        "lifecycleState": "completed",
        "reconciliationState": "matched",
        "provider": "stripe",
        "sourceRecordId": "pay-1",
        "evidenceRecordId": "pay-1-revision",
        "occurredAt": "2026-10-20T11:00:00+00:00",
        "observedAt": "2026-10-20T11:01:00+00:00",
        "ledgerCreatedAt": "2026-10-20T11:02:00+00:00",
        "ledgerUpdatedAt": "2026-10-20T11:03:00+00:00",
        "evidence": evidence if evidence is not None else [_evidence("pay-1-revision")],
    }


def _association(
    *,
    subject_kind: str = "campaign",
    subject_id: str = SUBJECT_ID,
    order_ref: str = "order-ref-1",
) -> dict[str, Any]:
    return {
        "commerceOrderRef": order_ref,
        "subjectKind": subject_kind,
        "subjectId": subject_id,
        "activityId": "activity-1",
        "silverTable": "silver_activities",
        "evidence": _evidence("activity-1", "event"),
    }


def _source_result(
    *,
    tenant_id: str = TENANT,
    subject_kind: str = "campaign",
    subject_id: str = SUBJECT_ID,
    facts: Optional[list[dict[str, Any]]] = None,
    associations: Optional[list[dict[str, Any]]] = None,
    truncated: bool = False,
    reason: Optional[str] = None,
) -> dict[str, Any]:
    id_field = {"campaign": "campaign_id", "entity": "entity_id", "journey": "journey_id"}[
        subject_kind
    ]
    result = {
        "_scope": {
            "tenantId": tenant_id,
            "subjectKind": subject_kind,
            "subjectId": subject_id,
        },
        id_field: subject_id,
        "join_basis": {
            "campaign": JOIN_BASIS,
            "entity": "explicit_canonical_profile_scoped_activity_commerce_order_ref",
            "journey": "explicit_journey_step_commerce_order_ref",
        }[subject_kind],
        "operation_links": [],
        "payment_facts": facts or [],
        "association_evidence": associations or [],
        "evidence_truncated": truncated,
        "invalid_order_reference_count": 0,
        "unresolved_order_references": 0,
        "ledger_read_errors": 0,
        "invalid_ledger_records": 0,
        "as_of": "2026-10-20T12:00:00+00:00",
    }
    if reason is not None:
        result["reason"] = reason
    return result


def _empty_source(tenant_id: str, subject_kind: str, subject_id: str) -> dict[str, Any]:
    return _source_result(
        tenant_id=tenant_id,
        subject_kind=subject_kind,
        subject_id=subject_id,
    )


@pytest.mark.asyncio
async def test_emits_exact_slots_and_only_evidence_backed_purchase_value_and_campaign_link_claims() -> (
    None
):
    request = _request()
    source = FakeCommerceSource(_source_result(facts=[_fact()], associations=[_association()]))
    result = await Commerce360Provider(source).project(request, _context(request))

    assert tuple(section.id for section in result.sections) == OUTPUT_SECTIONS
    sections = {section.id: section for section in result.sections}
    assert sections["purchase"].state == "available"
    assert sections["value"].state == "available"
    assert sections["campaign_links"].state == "available"
    assert sections["evidence_trace"].state == "available"
    assert (
        sections["purchase"].content["purchaseFacts"][0]["occurredAt"]
        == "2026-10-20T11:00:00+00:00"
    )
    assert sections["value"].content["aggregation"] == "not_aggregated"
    assert sections["value"].content["values"][0]["amountUsd"] == "25.00"

    for slot in (
        "product_offer_summary",
        "catalog_links",
        "exposures",
        "intent",
        "cart_checkout",
        "availability_price",
        "risk",
    ):
        assert sections[slot].state == "unknown"
        assert sections[slot].content["reasonCodes"]

    claims_by_slot: dict[str, list[Any]] = {}
    for claim in result.claims:
        for slot in claim.domainSlotIds or []:
            claims_by_slot.setdefault(slot, []).append(claim)
    assert set(claims_by_slot) == {"purchase", "value", "campaign_links", "evidence_trace"}
    assert all(claim.evidenceRefs for claim in result.claims)


@pytest.mark.asyncio
async def test_fails_closed_on_request_context_tenant_mismatch_without_reading_source() -> None:
    request = _request()
    source = FakeCommerceSource(_source_result())
    result = await Commerce360Provider(source).project(
        request,
        _context(request, tenant_id="tenant-b"),
    )

    assert source.calls == []
    sections = {section.id: section for section in result.sections}
    assert sections["purchase"].state == "degraded"
    assert (
        "commerce_projection_context_scope_mismatch" in sections["purchase"].content["reasonCodes"]
    )
    assert sections["product_offer_summary"].state == "unknown"
    assert result.claims == []


@pytest.mark.asyncio
async def test_rejects_wrong_source_tenant_or_subject_scope() -> None:
    request = _request()
    wrong_scope = _source_result(tenant_id="tenant-b", facts=[_fact()])
    result = await Commerce360Provider(FakeCommerceSource(wrong_scope)).project(
        request,
        _context(request),
    )

    sections = {section.id: section for section in result.sections}
    assert sections["purchase"].state == "unknown"
    assert sections["purchase"].content["purchaseFacts"] == []
    assert result.claims == []


@pytest.mark.asyncio
async def test_partial_source_retains_valid_fact_and_marks_supported_slots_degraded() -> None:
    request = _request()
    result = await Commerce360Provider(
        FakeCommerceSource(_source_result(facts=[_fact()], truncated=True))
    ).project(request, _context(request))

    sections = {section.id: section for section in result.sections}
    assert sections["purchase"].state == "degraded"
    assert sections["purchase"].content["purchaseFacts"][0]["factId"].startswith("commerce:")
    assert sections["value"].state == "degraded"
    assert any(claim.domainSlotIds == ["purchase"] for claim in result.claims)


@pytest.mark.asyncio
async def test_empty_scoped_read_is_distinct_from_unavailable_source() -> None:
    request = _request()
    empty = await Commerce360Provider(FakeCommerceSource()).project(request, _context(request))
    unavailable = await Commerce360Provider(FakeCommerceSource(fail=True)).project(
        request,
        _context(request),
    )

    empty_sections = {section.id: section for section in empty.sections}
    unavailable_sections = {section.id: section for section in unavailable.sections}
    assert empty_sections["purchase"].state == "empty"
    assert empty_sections["value"].state == "empty"
    assert unavailable_sections["purchase"].state == "degraded"
    assert "sensitive storage failure detail" not in str(unavailable.model_dump(mode="json"))


@pytest.mark.asyncio
async def test_campaign_links_remain_unknown_for_profile_and_journey_subjects() -> None:
    for subject_kind, subject_id in (("entity", "profile-1"), ("journey", "journey-1")):
        request = _request(subject_kind=subject_kind, subject_id=subject_id)
        source = FakeCommerceSource(
            _source_result(
                subject_kind=subject_kind,
                subject_id=subject_id,
                facts=[
                    _fact(
                        join_basis={
                            "entity": "explicit_canonical_profile_scoped_activity_commerce_order_ref",
                            "journey": "explicit_journey_step_commerce_order_ref",
                        }[subject_kind]
                    )
                ],
            )
        )
        result = await Commerce360Provider(source).project(request, _context(request))
        sections = {section.id: section for section in result.sections}
        assert sections["campaign_links"].state == "unknown"
        assert sections["purchase"].state == "available"
        assert not any("campaign_links" in (claim.domainSlotIds or []) for claim in result.claims)


@pytest.mark.asyncio
async def test_product_offer_and_checkout_subjects_keep_all_slots_unknown_without_authority() -> (
    None
):
    unsupported_kinds = ("commerce", "product", "offer", "sku", "checkout")
    for subject_kind in unsupported_kinds:
        request = _request(subject_kind=subject_kind, subject_id=f"{subject_kind}-1")
        source = FakeCommerceSource(
            {
                "_scope": {
                    "tenantId": TENANT,
                    "subjectKind": subject_kind,
                    "subjectId": request.subject.id,
                },
                "join_basis": "unsupported_subject_kind",
                "reason": "commerce_operation_subject_kind_not_supported",
            }
        )
        result = await Commerce360Provider(source).project(request, _context(request))
        sections = {section.id: section for section in result.sections}
        if subject_kind in {"product", "offer"}:
            # The intent authority distinguishes a missing canonical catalog
            # subject from an unavailable join. It still emits no intent data.
            assert sections["intent"].state == "missing"
            assert all(
                section.state == "unknown"
                for section_id, section in sections.items()
                if section_id != "intent"
            )
        else:
            assert all(section.state == "unknown" for section in sections.values())
        assert result.claims == []


@pytest.mark.asyncio
async def test_duplicate_and_over_limit_facts_are_bounded_and_degrade_source() -> None:
    request = _request()
    source_facts = [
        _fact(
            fact_id=f"commerce:abc:payment:stripe:pay-{index}:hash",
            evidence=[_evidence(f"pay-{index}")],
        )
        for index in range(501)
    ]
    source_facts.append(source_facts[0])
    result = await Commerce360Provider(
        FakeCommerceSource(_source_result(facts=source_facts))
    ).project(request, _context(request))

    sections = {section.id: section for section in result.sections}
    assert sections["purchase"].state == "degraded"
    assert len(sections["purchase"].content["purchaseFacts"]) == 500
    assert len({fact["factId"] for fact in sections["purchase"].content["purchaseFacts"]}) == 500


def test_register_provider_requires_central_projection_definition() -> None:
    if "commerce360" not in INTELLIGENCE_PROJECTION_DEFINITIONS:
        pytest.skip("root-owned technical projection row is pending")
    registry = ProviderRegistry(registry_data=INTELLIGENCE_PROJECTION_DEFINITIONS)
    register_provider(registry)
    assert registry.get("commerce360") is not None


def test_provider_registration_does_not_claim_non_read_only_behavior() -> None:
    provider = Commerce360Provider(FakeCommerceSource())
    assert provider.graph_mutation_policy == "read_only"
    assert provider.projection_id == "commerce360"
    assert provider.contract_version == INTELLIGENCE_PROJECTIONS_CONTRACT_VERSION


def _catalog_evidence(record_id: str) -> list[EvidenceRef]:
    return [
        EvidenceRef(
            id=record_id,
            type="document",
            source="catalog-source",
            observedAt="2026-10-20T10:00:00+00:00",
        )
    ]


def _product_record(
    *, tenant_id: str = TENANT, product_id: str = "prod-1", revision: str = "prod-r1"
) -> CommerceProductRecord:
    source_record_id = f"source:{product_id}:{revision}"
    return CommerceProductRecord(
        tenant_id=tenant_id,
        product_id=product_id,
        title="Product one",
        description="A catalog product",
        lifecycle_state="active",
        valid_from="2026-10-01T00:00:00+00:00",
        valid_to=None,
        observed_at="2026-10-20T10:00:00+00:00",
        source_provider="catalog-source",
        source_record_id=source_record_id,
        source_revision_id=revision,
        evidence_refs=[
            EvidenceRef(
                id=source_record_id,
                type="document",
                source="catalog-source",
                observedAt="2026-10-20T10:00:00+00:00",
            )
        ],
    )


def _offer_record(
    *,
    tenant_id: str = TENANT,
    offer_id: str = "offer-1",
    product_id: str = "prod-1",
    revision: str = "offer-r1",
) -> CommerceOfferRecord:
    source_record_id = f"source:{offer_id}:{revision}"
    return CommerceOfferRecord(
        tenant_id=tenant_id,
        offer_id=offer_id,
        product_id=product_id,
        title="Offer one",
        description="An explicit product offer",
        lifecycle_state="active",
        valid_from="2026-10-01T00:00:00+00:00",
        valid_to=None,
        observed_at="2026-10-20T10:01:00+00:00",
        source_provider="catalog-source",
        source_record_id=source_record_id,
        source_revision_id=revision,
        evidence_refs=[
            EvidenceRef(
                id=source_record_id,
                type="document",
                source="catalog-source",
                observedAt="2026-10-20T10:01:00+00:00",
            )
        ],
    )


@pytest.mark.asyncio
async def test_product_and_offer_catalog_reads_emit_exact_evidence_backed_claims() -> None:
    repository = CommerceProductOfferCatalogRepository()
    repository._local_products.clear()
    repository._local_offers.clear()
    product = _product_record()
    offer = _offer_record()
    await repository.record_product(product)
    await repository.record_offer(offer)
    catalog = RepositoryCommerceProductOfferCatalogEvidenceSource(repository)

    for subject_kind, subject_id in (("product", "prod-1"), ("offer", "offer-1")):
        request = _request(
            subject_kind=subject_kind,
            subject_id=subject_id,
            projectionId="commerce360",
        )
        result = await Commerce360Provider(FakeCommerceSource(), catalog).project(
            request, _context(request)
        )
        sections = {section.id: section for section in result.sections}
        summary = sections["product_offer_summary"]
        links = sections["catalog_links"]
        assert summary.state == "available"
        assert summary.content["product"]["productId"] == "prod-1"
        assert summary.content["product"]["lifecycleState"] == "active"
        assert summary.content["offers"][0]["offerId"] == "offer-1"
        assert links.state == "available"
        assert links.content["links"][0]["productResolved"] is True
        assert {ref["id"] for ref in links.content["links"][0]["offerEvidence"]} == {
            offer.source_record_id
        }
        assert {ref["id"] for ref in links.content["links"][0]["productEvidence"]} == {
            product.source_record_id
        }
        claims_by_slot = {
            slot: [claim for claim in result.claims if slot in (claim.domainSlotIds or [])]
            for slot in ("product_offer_summary", "catalog_links")
        }
        assert len(claims_by_slot["product_offer_summary"]) == 1
        assert len(claims_by_slot["catalog_links"]) == 1
        assert all(claim.evidenceRefs for claims in claims_by_slot.values() for claim in claims)


@pytest.mark.asyncio
async def test_catalog_read_is_tenant_scoped_and_current_product_without_offers_is_empty() -> None:
    repository = CommerceProductOfferCatalogRepository()
    repository._local_products.clear()
    repository._local_offers.clear()
    await repository.record_product(_product_record())
    catalog = RepositoryCommerceProductOfferCatalogEvidenceSource(repository)

    request = _request(
        subject_kind="product",
        subject_id="prod-1",
        tenant_id="tenant-b",
        projectionId="commerce360",
    )
    result = await Commerce360Provider(FakeCommerceSource(), catalog).project(
        request, _context(request)
    )
    sections = {section.id: section for section in result.sections}
    assert sections["product_offer_summary"].state == "missing"
    assert sections["catalog_links"].state == "missing"
    assert not any(
        claim.domainSlotIds
        and set(claim.domainSlotIds) & {"product_offer_summary", "catalog_links"}
        for claim in result.claims
    )

    request = _request(subject_kind="product", subject_id="prod-1", projectionId="commerce360")
    result = await Commerce360Provider(FakeCommerceSource(), catalog).project(
        request, _context(request)
    )
    sections = {section.id: section for section in result.sections}
    assert sections["product_offer_summary"].state == "available"
    assert sections["catalog_links"].state == "empty"
    assert sections["catalog_links"].content["links"] == []


@pytest.mark.asyncio
async def test_catalog_summary_preserves_retired_lifecycle_and_validity_dates() -> None:
    repository = CommerceProductOfferCatalogRepository()
    repository._local_products.clear()
    repository._local_offers.clear()
    product = _product_record(revision="prod-r2").model_copy(
        update={
            "lifecycle_state": "retired",
            "valid_to": datetime.fromisoformat("2026-10-15T00:00:00+00:00"),
        }
    )
    await repository.record_product(product)
    catalog = RepositoryCommerceProductOfferCatalogEvidenceSource(repository)
    request = _request(subject_kind="product", subject_id="prod-1", projectionId="commerce360")

    result = await Commerce360Provider(FakeCommerceSource(), catalog).project(
        request, _context(request)
    )

    section = next(section for section in result.sections if section.id == "product_offer_summary")
    assert section.state == "available"
    assert section.content["product"]["lifecycleState"] == "retired"
    assert section.content["product"]["validTo"] == "2026-10-15T00:00:00+00:00"
    assert section.content["asOf"] == request.asOf
    availability_price = next(
        section for section in result.sections if section.id == "availability_price"
    )
    assert availability_price.state == "degraded"
    lifecycle_record = availability_price.content["catalogLifecycleRecords"][0]
    assert lifecycle_record["lifecycleState"] == "retired"
    assert lifecycle_record["validTo"] == "2026-10-15T00:00:00+00:00"
    assert availability_price.content["availability"]["state"] == "unknown"
    assert availability_price.content["price"]["state"] == "unknown"
    assert availability_price.content["freshness"]["state"] == "unknown"
    assert "retired" in result.claims[-1].claims[0]


class FakeCatalogSource:
    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result

    async def read(self, tenant_id, subject, *, as_of):
        return self.result


@pytest.mark.asyncio
async def test_catalog_offer_product_mismatch_and_as_of_mismatch_fail_closed() -> None:
    request = _request(subject_kind="offer", subject_id="offer-1", projectionId="commerce360")
    result = {
        "_scope": {"tenantId": TENANT, "subjectKind": "offer", "subjectId": "offer-1"},
        "join_basis": "tenant_scoped_canonical_offer_product_id",
        "sourceState": "available",
        "reason": None,
        "product": _product_record(product_id="prod-other").model_dump(mode="json"),
        "offers": [_offer_record().model_dump(mode="json")],
        "truncated": False,
        "asOf": request.asOf,
    }
    for source_result in (
        result,
        {
            **result,
            "product": _product_record().model_dump(mode="json"),
            "asOf": "2026-10-20T11:00:00+00:00",
        },
    ):
        projected = await Commerce360Provider(
            FakeCommerceSource(), FakeCatalogSource(source_result)
        ).project(request, _context(request))
        sections = {section.id: section for section in projected.sections}
        assert sections["product_offer_summary"].state == "unknown"
        assert sections["catalog_links"].state == "unknown"
        assert sections["availability_price"].state == "unknown"
        assert not any(
            claim.domainSlotIds
            and set(claim.domainSlotIds)
            & {"product_offer_summary", "catalog_links", "availability_price"}
            for claim in projected.claims
        )


@pytest.mark.asyncio
async def test_availability_price_is_partial_only_for_exact_tenant_catalog_evidence() -> None:
    repository = CommerceProductOfferCatalogRepository()
    repository._local_products.clear()
    repository._local_offers.clear()
    await repository.record_product(_product_record())
    await repository.record_offer(_offer_record())
    catalog = RepositoryCommerceProductOfferCatalogEvidenceSource(repository)

    for subject_kind, subject_id, join_basis in (
        ("product", "prod-1", "tenant_scoped_canonical_product_id"),
        ("offer", "offer-1", "tenant_scoped_canonical_offer_product_id"),
    ):
        request = _request(subject_kind=subject_kind, subject_id=subject_id)
        result = await Commerce360Provider(FakeCommerceSource(), catalog).project(
            request,
            _context(request),
        )
        section = next(section for section in result.sections if section.id == "availability_price")

        assert section.state == "degraded"
        assert section.content["joinBasis"] == join_basis
        assert section.content["catalogLifecycleRecords"]
        assert section.content["availability"] == {
            "state": "unknown",
            "reasonCode": "commerce_inventory_authority_not_connected",
        }
        assert section.content["price"] == {
            "state": "unknown",
            "reasonCode": "commerce_offer_price_authority_not_connected",
        }
        assert section.content["freshness"]["state"] == "unknown"
        assert section.content["freshness"]["catalogRecordTimestampFieldsIncluded"] is True
        assert (
            "commerce_availability_price_authority_not_connected" in section.content["reasonCodes"]
        )
        assert not any(
            field in section.content
            for field in ("unitPrice", "quantityAvailable", "stockQuantity", "sellable")
        )
        lifecycle_claims = [
            claim for claim in result.claims if "availability_price" in (claim.domainSlotIds or [])
        ]
        assert lifecycle_claims
        assert all(claim.evidenceRefs for claim in lifecycle_claims)

    missing_request = _request(subject_kind="product", subject_id="prod-1", tenant_id="tenant-b")
    missing_result = await Commerce360Provider(FakeCommerceSource(), catalog).project(
        missing_request,
        _context(missing_request),
    )
    missing_section = next(
        section for section in missing_result.sections if section.id == "availability_price"
    )
    assert missing_section.state == "unknown"
    assert missing_section.content["catalogLifecycleRecords"] == []
    assert not any(
        "availability_price" in (claim.domainSlotIds or []) for claim in missing_result.claims
    )


@pytest.mark.asyncio
async def test_catalog_truncation_degrades_completeness_and_caps_exposed_records() -> None:
    request = _request(subject_kind="product", subject_id="prod-1", projectionId="commerce360")
    product = _product_record().model_dump(mode="json")
    offers = [
        _offer_record(offer_id=f"offer-{index}", revision=f"rev-{index}").model_dump(mode="json")
        for index in range(501)
    ]
    source = FakeCatalogSource(
        {
            "_scope": {"tenantId": TENANT, "subjectKind": "product", "subjectId": "prod-1"},
            "join_basis": "tenant_scoped_canonical_product_id",
            "sourceState": "degraded",
            "reason": "commerce_catalog_offer_list_truncated",
            "product": product,
            "offers": offers,
            "truncated": True,
            "asOf": request.asOf,
        }
    )
    result = await Commerce360Provider(FakeCommerceSource(), source).project(
        request, _context(request)
    )
    sections = {section.id: section for section in result.sections}
    assert sections["product_offer_summary"].state == "degraded"
    assert sections["catalog_links"].state == "degraded"
    assert sections["availability_price"].state == "degraded"
    assert (
        "commerce_catalog_offer_list_truncated"
        in sections["availability_price"].content["reasonCodes"]
    )
    assert sections["product_offer_summary"].content["sourceCompleteness"] == "partial"
    assert len(sections["product_offer_summary"].content["offers"]) == 500
