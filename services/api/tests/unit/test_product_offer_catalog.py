"""Tests for immutable, tenant-scoped Commerce product and offer revisions."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pytest
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")

from graph.operational_intelligence.models import EvidenceRef  # noqa: E402
from value.commerce import product_offer_catalog as catalog  # noqa: E402
from value.commerce.product_offer_catalog import (  # noqa: E402
    CommerceOfferRecord,
    CommerceProductOfferCatalogRepository,
    CommerceProductRecord,
)


AS_OF_1 = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
AS_OF_2 = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)


def _product(
    *,
    tenant_id: str = "tenant-a",
    product_id: str = "product-1",
    revision: str = "product-r1",
    observed_at: datetime = datetime(2026, 10, 20, 10, tzinfo=timezone.utc),
    title: str = "Product",
    lifecycle_state: str = "active",
) -> CommerceProductRecord:
    source_record_id = f"source:{product_id}:{revision}"
    return CommerceProductRecord(
        tenant_id=tenant_id,
        product_id=product_id,
        title=title,
        description=None,
        lifecycle_state=lifecycle_state,
        valid_from=None,
        valid_to=None,
        observed_at=observed_at,
        source_provider="catalog-source",
        source_record_id=source_record_id,
        source_revision_id=revision,
        evidence_refs=[
            EvidenceRef(
                id=source_record_id,
                type="document",
                source="catalog-source",
                observedAt=observed_at.isoformat(),
            )
        ],
    )


def _offer(
    *,
    tenant_id: str = "tenant-a",
    offer_id: str = "offer-1",
    product_id: str = "product-1",
    revision: str = "offer-r1",
    observed_at: datetime = datetime(2026, 10, 20, 11, tzinfo=timezone.utc),
) -> CommerceOfferRecord:
    source_record_id = f"source:{offer_id}:{revision}"
    return CommerceOfferRecord(
        tenant_id=tenant_id,
        offer_id=offer_id,
        product_id=product_id,
        title="Offer",
        description=None,
        lifecycle_state="active",
        valid_from=None,
        valid_to=None,
        observed_at=observed_at,
        source_provider="catalog-source",
        source_record_id=source_record_id,
        source_revision_id=revision,
        evidence_refs=[
            EvidenceRef(
                id=source_record_id,
                type="document",
                source="catalog-source",
                observedAt=observed_at.isoformat(),
            )
        ],
    )


@pytest.fixture(autouse=True)
def clear_local_catalog() -> None:
    catalog._LOCAL_PRODUCTS.clear()
    catalog._LOCAL_OFFERS.clear()


@pytest.mark.asyncio
async def test_product_revisions_are_immutable_and_selected_as_of() -> None:
    repository = CommerceProductOfferCatalogRepository()
    first = _product()
    second = _product(
        revision="product-r2",
        observed_at=datetime(2026, 10, 21, 10, tzinfo=timezone.utc),
        title="Updated product",
    )
    await repository.record_product(first)
    await repository.record_product(second)

    assert (await repository.get_product("tenant-a", "product-1", as_of=AS_OF_1)) == first
    assert (await repository.get_product("tenant-a", "product-1")) == second
    assert await repository.get_product("tenant-b", "product-1") is None

    with pytest.raises(ValueError, match="revision id reused"):
        await repository.record_product(
            _product(revision="product-r1", title="Conflicting content")
        )


@pytest.mark.asyncio
async def test_offer_must_reference_a_product_owned_by_the_same_tenant() -> None:
    repository = CommerceProductOfferCatalogRepository()
    await repository.record_product(_product())
    with pytest.raises(ValueError, match="existing tenant product"):
        await repository.record_offer(_offer(tenant_id="tenant-b"))

    await repository.record_product(_product(tenant_id="tenant-b"))
    assert await repository.record_offer(_offer(tenant_id="tenant-b"))


@pytest.mark.asyncio
async def test_offer_lists_use_latest_revision_link_and_honor_as_of_and_bound() -> None:
    repository = CommerceProductOfferCatalogRepository()
    await repository.record_product(_product(product_id="product-1"))
    await repository.record_product(_product(product_id="product-2"))
    await repository.record_offer(_offer(offer_id="offer-moved", product_id="product-1"))
    moved_at = datetime(2026, 10, 21, 10, tzinfo=timezone.utc)
    await repository.record_offer(
        _offer(
            offer_id="offer-moved",
            product_id="product-2",
            revision="offer-r2",
            observed_at=moved_at,
        )
    )
    await repository.record_offer(_offer(offer_id="offer-second", product_id="product-1"))

    old_links, old_truncated = await repository.list_offers_for_product(
        "tenant-a", "product-1", as_of=AS_OF_1
    )
    current_links, current_truncated = await repository.list_offers_for_product(
        "tenant-a", "product-1"
    )
    bounded, truncated = await repository.list_offers_for_product(
        "tenant-a", "product-1", as_of=AS_OF_1, limit=1
    )

    assert {record.offer_id for record in old_links} == {"offer-moved", "offer-second"}
    assert old_truncated is False
    assert [record.offer_id for record in current_links] == ["offer-second"]
    assert current_truncated is False
    assert len(bounded) == 1
    assert truncated is True


@pytest.mark.asyncio
async def test_repository_rejects_naive_as_of_and_invalid_catalog_records() -> None:
    repository = CommerceProductOfferCatalogRepository()
    with pytest.raises(ValueError, match="as_of must include a timezone"):
        await repository.get_product("tenant-a", "product-1", as_of=datetime(2026, 10, 20, 12))
    with pytest.raises(ValidationError, match="lifecycle_state"):
        _product(lifecycle_state="available")
    with pytest.raises(ValidationError, match="include a timezone"):
        CommerceProductRecord.model_validate(
            {
                **_product().model_dump(mode="json"),
                "observed_at": "2026-10-20T10:00:00",
            }
        )
    with pytest.raises(ValidationError, match="exact source record"):
        CommerceOfferRecord.model_validate(
            {
                **_offer().model_dump(mode="json"),
                "evidence_refs": [
                    EvidenceRef(
                        id="different-record",
                        type="document",
                        source="catalog-source",
                    ).model_dump(mode="json")
                ],
            }
        )


class _FakeConnection:
    def __init__(self, product_data: dict[str, Any]) -> None:
        self.product_data = product_data
        self.fetchrow_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.fetch_calls: list[tuple[str, tuple[Any, ...]]] = []

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any]:
        self.fetchrow_calls.append((query, args))
        return {"data": self.product_data}

    async def fetch(self, query: str, *args: Any) -> list[Any]:
        self.fetch_calls.append((query, args))
        return []


class _Acquire:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    async def __aenter__(self) -> _FakeConnection:
        return self.connection

    async def __aexit__(self, *_: Any) -> None:
        return None


class _FakePool:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    def acquire(self) -> _Acquire:
        return _Acquire(self.connection)


@pytest.mark.asyncio
async def test_production_reads_bind_exact_tenant_subject_and_as_of_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _product().model_dump(mode="json")
    connection = _FakeConnection(row)
    pool = _FakePool(connection)

    async def get_fake_pool() -> _FakePool:
        return pool

    monkeypatch.setattr(catalog, "_LOCAL", False)
    monkeypatch.setattr(catalog, "get_pool", get_fake_pool)
    repository = CommerceProductOfferCatalogRepository()
    await repository.get_product("tenant-a", "product-1", as_of=AS_OF_1)
    await repository.list_offers_for_product("tenant-a", "product-1", as_of=AS_OF_1, limit=8)

    product_query, product_args = connection.fetchrow_calls[0]
    assert "WHERE tenant_id=$1 AND product_id=$2 AND observed_at <= $3" in product_query
    assert product_args == ("tenant-a", "product-1", AS_OF_1)
    offer_query, offer_args = connection.fetch_calls[0]
    assert "WHERE tenant_id=$1 AND product_id=$3" in offer_query
    assert "WHERE tenant_id=$1 AND offer_id=candidate.offer_id" in offer_query
    assert offer_args == ("tenant-a", AS_OF_1, "product-1", 9)
