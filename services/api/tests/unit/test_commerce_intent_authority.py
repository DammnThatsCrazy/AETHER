"""Commerce intent authority tests for exact tenant/product/offer joins."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

import pytest
from fastapi import HTTPException

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from graph.operational_intelligence.models import EvidenceRef  # noqa: E402
from shared.intelligence_projections import (  # noqa: E402
    ProjectionContext,
    ProjectionRequest,
    ProjectionSubject,
)
from value.commerce import commerce360_provider as commerce360  # noqa: E402
from value.commerce import commerce_intents as intent_module  # noqa: E402
from value.commerce import routes as commerce_routes  # noqa: E402
from value.commerce.commerce_intents import (  # noqa: E402
    CommerceIntentDeclaration,
    CommerceIntentIdempotencyConflict,
    CommerceIntentRecord,
    CommerceIntentRepository,
    CommerceIntentSubjectNotFound,
)
from value.commerce.commerce360_provider import (  # noqa: E402
    Commerce360Provider,
    RepositoryCommerceIntentEvidenceSource,
)
from value.commerce.product_offer_catalog import (  # noqa: E402
    CommerceOfferRecord,
    CommerceProductOfferCatalogRepository,
    CommerceProductRecord,
)


TENANT = "commerce-intent-tenant"
PRODUCT = "commerce-intent-product"
NOW = datetime.now(timezone.utc).replace(microsecond=0)


def _run(coro):
    return asyncio.run(coro)


def _product(*, tenant_id: str = TENANT, product_id: str = PRODUCT) -> CommerceProductRecord:
    source_record_id = f"catalog:{product_id}:r1"
    observed_at = NOW - timedelta(minutes=10)
    return CommerceProductRecord(
        tenant_id=tenant_id,
        product_id=product_id,
        title="Intent test product",
        description=None,
        lifecycle_state="active",
        valid_from=None,
        valid_to=None,
        observed_at=observed_at,
        source_provider="catalog-test",
        source_record_id=source_record_id,
        source_revision_id="r1",
        evidence_refs=[
            EvidenceRef(
                id=source_record_id,
                type="document",
                source="catalog-test",
                observedAt=observed_at.isoformat(),
            )
        ],
    )


def _offer(
    *, tenant_id: str = TENANT, offer_id: str = "commerce-intent-offer"
) -> CommerceOfferRecord:
    source_record_id = f"catalog:{offer_id}:r1"
    observed_at = NOW - timedelta(minutes=5)
    return CommerceOfferRecord(
        tenant_id=tenant_id,
        offer_id=offer_id,
        product_id=PRODUCT,
        title="Intent test offer",
        description=None,
        lifecycle_state="active",
        valid_from=None,
        valid_to=None,
        observed_at=observed_at,
        source_provider="catalog-test",
        source_record_id=source_record_id,
        source_revision_id="r1",
        evidence_refs=[
            EvidenceRef(
                id=source_record_id,
                type="document",
                source="catalog-test",
                observedAt=observed_at.isoformat(),
            )
        ],
    )


def _declaration(
    *,
    key: str = "intent-key-1",
    intent_id: Optional[str] = None,
    subject_id: str = PRODUCT,
    intent_kind: str = "purchase",
    state: str = "declared",
    effective_at: Optional[datetime] = None,
) -> CommerceIntentDeclaration:
    return CommerceIntentDeclaration(
        idempotency_key=key,
        intent_id=intent_id,
        subject_kind="product",
        subject_id=subject_id,
        intent_kind=intent_kind,
        state=state,
        effective_at=effective_at,
    )


class _OperationSource:
    async def read(self, tenant_id, subject, *, as_of):
        return {
            "_scope": {
                "tenantId": tenant_id,
                "subjectKind": subject.kind,
                "subjectId": subject.id,
            },
            "join_basis": "unsupported_subject_kind",
            "reason": "commerce_operation_subject_kind_not_supported",
        }


def _projection_request(
    *,
    tenant_id: str = TENANT,
    subject_id: str = PRODUCT,
    subject_kind: str = "product",
    as_of=None,
):
    anchor = as_of or (datetime.now(timezone.utc) + timedelta(minutes=5))
    return ProjectionRequest(
        projectionId="commerce360",
        tenantId=tenant_id,
        subject=ProjectionSubject(kind=subject_kind, id=subject_id),
        asOf=anchor.isoformat(),
    )


def _context(request: ProjectionRequest) -> ProjectionContext:
    return ProjectionContext(
        projectionId="commerce360",
        tenantId=request.tenantId,
        registryState="implemented",
        dependencyState=[],
        asOf=request.asOf,
        warnings=[],
    )


@pytest.fixture(autouse=True)
def clear_local_intents():
    intent_module._LOCAL_INTENTS.clear()
    yield
    intent_module._LOCAL_INTENTS.clear()


@pytest.mark.asyncio
async def test_explicit_declarations_are_tenant_scoped_idempotent_and_revisioned() -> None:
    catalog = CommerceProductOfferCatalogRepository()
    await catalog.record_product(_product())
    repository = CommerceIntentRepository(catalog=catalog)
    read_anchor = datetime.now(timezone.utc) + timedelta(seconds=10)

    first = await repository.record_declaration(TENANT, "human", "user-1", _declaration())
    replay = await repository.record_declaration(TENANT, "human", "user-1", _declaration())
    assert replay == first
    assert first.actor_kind == "human"
    assert first.actor_id == "user-1"
    assert first.source_provider == "aether_commerce_intent_api"
    assert first.source_revision_id == "intent-key-1"
    assert first.evidence_refs[0].id == first.source_record_id

    with pytest.raises(CommerceIntentIdempotencyConflict):
        await repository.record_declaration(
            TENANT, "human", "user-1", _declaration(intent_kind="comparison")
        )

    future_revision = await repository.record_declaration(
        TENANT,
        "human",
        "user-1",
        _declaration(
            key="intent-key-2",
            intent_id=first.intent_id,
            state="fulfilled",
            effective_at=read_anchor + timedelta(minutes=1),
        ),
    )
    before_update, truncated = await repository.list_for_subject(
        TENANT,
        "product",
        PRODUCT,
        as_of=read_anchor,
    )
    after_update, _ = await repository.list_for_subject(
        TENANT,
        "product",
        PRODUCT,
        as_of=read_anchor + timedelta(minutes=2),
    )
    assert not truncated
    assert [record.state for record in before_update] == ["declared"]
    assert [record.state for record in after_update] == ["fulfilled"]
    assert future_revision.intent_id == first.intent_id
    assert await repository.list_for_subject("other-tenant", "product", PRODUCT) == ([], False)


@pytest.mark.asyncio
async def test_declaration_requires_existing_same_tenant_canonical_subject() -> None:
    catalog = CommerceProductOfferCatalogRepository()
    await catalog.record_product(_product())
    repository = CommerceIntentRepository(catalog=catalog)
    with pytest.raises(CommerceIntentSubjectNotFound):
        await repository.record_declaration("other-tenant", "human", "user-2", _declaration())


@pytest.mark.asyncio
async def test_offer_intent_uses_exact_tenant_offer_reference() -> None:
    catalog = CommerceProductOfferCatalogRepository()
    await catalog.record_product(_product())
    offer = _offer()
    await catalog.record_offer(offer)
    repository = CommerceIntentRepository(catalog=catalog)
    declaration = CommerceIntentDeclaration(
        idempotency_key="offer-intent-key",
        subject_kind="offer",
        subject_id=offer.offer_id,
        intent_kind="subscription",
    )
    record = await repository.record_declaration(TENANT, "human", "user-offer", declaration)
    provider = Commerce360Provider(
        _OperationSource(),
        intent_source=RepositoryCommerceIntentEvidenceSource(repository, catalog),
    )
    request = _projection_request(subject_id=offer.offer_id, subject_kind="offer")
    result = await provider.project(request, _context(request))
    intent = next(section for section in result.sections if section.id == "intent")

    assert intent.state == "available"
    assert intent.content["intents"][0]["intentId"] == record.intent_id
    assert intent.content["intents"][0]["subjectKind"] == "offer"
    assert intent.content["intents"][0]["subjectId"] == offer.offer_id


@pytest.mark.asyncio
async def test_provider_projects_only_explicit_intent_with_actor_and_evidence() -> None:
    catalog = CommerceProductOfferCatalogRepository()
    await catalog.record_product(_product())
    repository = CommerceIntentRepository(catalog=catalog)
    record = await repository.record_declaration(TENANT, "human", "user-42", _declaration())
    source = RepositoryCommerceIntentEvidenceSource(repository, catalog)
    provider = Commerce360Provider(_OperationSource(), intent_source=source)
    request = _projection_request()
    result = await provider.project(request, _context(request))

    sections = {section.id: section for section in result.sections}
    intent = sections["intent"]
    assert intent.state == "available"
    assert intent.canonicalAuthorityRefs == [
        "commerce_intent_authority",
        "commerce_product_offer_graph",
        "source_provenance",
    ]
    projected = intent.content["intents"][0]
    assert projected["intentId"] == record.intent_id
    assert projected["subjectKind"] == "product"
    assert projected["subjectId"] == PRODUCT
    assert projected["actor"] == {"kind": "human", "id": "user-42"}
    assert projected["effectiveAt"]
    assert projected["observedAt"]
    assert projected["evidenceRefs"][0]["id"] == record.source_record_id
    assert intent.content["freshness"]["state"] == "unknown"
    assert intent.content["freshness"]["sourceTimestampsPreserved"] is True
    assert sections["evidence_trace"].state == "available"
    assert any(
        claim.domainSlotIds == ["intent", "evidence_trace"] and claim.evidenceRefs
        for claim in result.claims
    )


@pytest.mark.asyncio
async def test_empty_missing_and_truncated_intent_states_are_distinct() -> None:
    catalog = CommerceProductOfferCatalogRepository()
    await catalog.record_product(_product())
    repository = CommerceIntentRepository(catalog=catalog)
    intent_source = RepositoryCommerceIntentEvidenceSource(repository, catalog)
    provider = Commerce360Provider(_OperationSource(), intent_source=intent_source)

    empty_request = _projection_request()
    empty = await provider.project(empty_request, _context(empty_request))
    assert next(section for section in empty.sections if section.id == "intent").state == "empty"

    missing_request = _projection_request(subject_id="not-in-catalog")
    missing = await provider.project(missing_request, _context(missing_request))
    missing_intent = next(section for section in missing.sections if section.id == "intent")
    assert missing_intent.state == "missing"
    assert "commerce_intent_canonical_subject_not_found" in missing_intent.content["reasonCodes"]

    await repository.record_declaration(
        TENANT, "human", "user-1", _declaration(key="trunc-1", intent_id="intent-1")
    )
    await repository.record_declaration(
        TENANT,
        "human",
        "user-1",
        _declaration(key="trunc-2", intent_id="intent-2", intent_kind="comparison"),
    )
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(commerce360, "_MAX_INTENT_RECORDS", 1)
    try:
        truncated_request = _projection_request()
        truncated = await provider.project(truncated_request, _context(truncated_request))
    finally:
        monkeypatch.undo()
    truncated_intent = next(section for section in truncated.sections if section.id == "intent")
    assert truncated_intent.state == "degraded"
    assert truncated_intent.content["sourceCompleteness"] == "partial"
    assert truncated_intent.content["truncated"] is True
    assert len(truncated_intent.content["intents"]) == 1


@pytest.mark.asyncio
async def test_intent_authority_read_failure_stays_unknown_instead_of_empty() -> None:
    catalog = CommerceProductOfferCatalogRepository()
    await catalog.record_product(_product())

    class FailingRepository:
        async def list_for_subject(self, *args, **kwargs):
            raise RuntimeError("storage detail must not escape")

    source = RepositoryCommerceIntentEvidenceSource(FailingRepository(), catalog)  # type: ignore[arg-type]
    provider = Commerce360Provider(_OperationSource(), intent_source=source)
    request = _projection_request()
    result = await provider.project(request, _context(request))
    intent = next(section for section in result.sections if section.id == "intent")
    assert intent.state == "unknown"
    assert intent.content["reasonCodes"] == ["commerce_intent_authority_unavailable"]
    assert "storage detail" not in str(result.model_dump(mode="json"))


def test_provider_degrades_future_or_ambiguous_records_and_rejects_stale_anchor():
    anchor = datetime.now(timezone.utc).replace(microsecond=0)
    request = _projection_request(as_of=anchor)
    record = CommerceIntentRecord(
        tenant_id=TENANT,
        intent_id="intent-future",
        idempotency_key="future-key",
        subject_kind="product",
        subject_id=PRODUCT,
        intent_kind="purchase",
        state="declared",
        actor_kind="human",
        actor_id="user-future",
        effective_at=anchor + timedelta(minutes=1),
        observed_at=anchor - timedelta(minutes=1),
        source_provider="intent-source",
        source_record_id="intent-source-record",
        source_revision_id="intent-source-revision",
        evidence_refs=[
            EvidenceRef(
                id="intent-source-record",
                type="annotation",
                source="intent-source",
            )
        ],
    )
    raw = {
        "_scope": {
            "tenantId": TENANT,
            "subjectKind": "product",
            "subjectId": PRODUCT,
        },
        "join_basis": "explicit_tenant_scoped_product_intent_reference",
        "sourceState": "available",
        "reason": None,
        "records": [record.model_dump(mode="json"), record.model_dump(mode="json")],
        "truncated": False,
        "asOf": request.asOf,
        "sourceCompleteness": "complete",
        "authorityRefs": [
            "commerce_intent_authority",
            "commerce_product_offer_graph",
            "source_provenance",
        ],
    }
    provider = Commerce360Provider(_OperationSource())
    degraded = provider._validate_intent_result(raw, request, as_of=request.asOf)
    assert degraded["sourceState"] == "degraded"
    assert degraded["records"] == []
    assert degraded["sourceCompleteness"] == "partial"

    stale = {
        **raw,
        "records": [],
        "sourceState": "empty",
        "asOf": (anchor - timedelta(seconds=1)).isoformat(),
    }
    rejected = provider._validate_intent_result(stale, request, as_of=request.asOf)
    assert rejected["sourceState"] == "unknown"
    assert rejected["reason"] == "commerce_intent_as_of_scope_mismatch"


def test_commerce_intent_route_binds_actor_and_enforces_idempotency(monkeypatch) -> None:
    catalog = CommerceProductOfferCatalogRepository()
    _run(catalog.record_product(_product()))
    repository = CommerceIntentRepository(catalog=catalog)
    monkeypatch.setattr(commerce_routes, "_commerce_intents", repository)

    class Tenant:
        tenant_id = TENANT
        user_id = "authenticated-user"

        def require_permission(self, permission):
            assert permission == "commerce:write"

    request = SimpleNamespace(state=SimpleNamespace(tenant=Tenant()))
    body = _declaration(key="route-intent")
    first = _run(commerce_routes.record_commerce_intent(body, request))["data"]
    replay = _run(commerce_routes.record_commerce_intent(body, request))["data"]
    assert first == replay
    assert first["actor_kind"] == "human"
    assert first["actor_id"] == "authenticated-user"

    conflict = _declaration(key="route-intent", intent_kind="comparison")
    with pytest.raises(HTTPException) as exc:
        _run(commerce_routes.record_commerce_intent(conflict, request))
    assert exc.value.status_code == 409

    Tenant.user_id = None
    with pytest.raises(HTTPException) as no_principal:
        _run(commerce_routes.record_commerce_intent(_declaration(key="no-principal"), request))
    assert no_principal.value.status_code == 403
