"""Canonical tenant-scoped product and offer catalog authority.

Commerce360 reads this store but never writes it. Connector or reviewed import
code writes immutable source revisions through :class:`CommerceProductOfferCatalogRepository`.
Product/offer relationships are explicit ``product_id`` references from an
offer record; conversions and transaction line items are not used to create or
infer catalog records.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from graph.operational_intelligence.models import EvidenceRef
from repositories.repos import get_pool


CommerceCatalogLifecycle = Literal["draft", "active", "paused", "retired", "expired"]
_LOCAL = os.getenv("AETHER_ENV", "local").lower() == "local"
_MAX_EVIDENCE_REFS = 32
_LOCAL_PRODUCTS: dict[tuple[str, str, str], dict[str, Any]] = {}
_LOCAL_OFFERS: dict[tuple[str, str, str], dict[str, Any]] = {}


def _parse_instant(value: Any, field_name: str) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field_name} must be an ISO-8601 timestamp") from exc
    else:
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp")
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed.astimezone(timezone.utc)


class _CatalogRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=256)
    description: Optional[str] = Field(default=None, max_length=2048)
    lifecycle_state: CommerceCatalogLifecycle
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    observed_at: datetime
    source_provider: str = Field(min_length=1, max_length=96)
    source_record_id: str = Field(min_length=1, max_length=512)
    source_revision_id: str = Field(min_length=1, max_length=512)
    evidence_refs: list[EvidenceRef] = Field(min_length=1, max_length=_MAX_EVIDENCE_REFS)

    @model_validator(mode="before")
    @classmethod
    def normalize_instants(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        normalized = dict(values)
        for name in ("valid_from", "valid_to", "observed_at"):
            if name in normalized:
                normalized[name] = _parse_instant(normalized[name], name)
        return normalized

    @model_validator(mode="after")
    def validate_provenance_and_validity(self) -> "_CatalogRecord":
        for name in (
            "tenant_id",
            "title",
            "source_provider",
            "source_record_id",
            "source_revision_id",
        ):
            value = getattr(self, name)
            if not value.strip() or any(ord(char) < 32 for char in value):
                raise ValueError(f"{name} must be non-empty text without control characters")
        if self.valid_from and self.valid_to and self.valid_from >= self.valid_to:
            raise ValueError("valid_to must be later than valid_from")
        if not any(
            ref.source == self.source_provider and ref.id == self.source_record_id
            for ref in self.evidence_refs
        ):
            raise ValueError("evidence_refs must include the exact source record")
        return self


class CommerceProductRecord(_CatalogRecord):
    """One immutable source revision for a tenant's commercial product."""

    product_id: str = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def validate_product_identity(self) -> "CommerceProductRecord":
        _validate_identifier(self.product_id, "product_id")
        return self


class CommerceOfferRecord(_CatalogRecord):
    """One immutable offer revision with an explicit product reference."""

    offer_id: str = Field(min_length=1, max_length=256)
    product_id: str = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def validate_offer_identity(self) -> "CommerceOfferRecord":
        _validate_identifier(self.offer_id, "offer_id")
        _validate_identifier(self.product_id, "product_id")
        return self


def _validate_identifier(value: str, field_name: str) -> None:
    if not value.strip() or any(ord(char) < 32 for char in value):
        raise ValueError(f"{field_name} must be non-empty text without control characters")


def _normalize_as_of(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError("as_of must include a timezone")
    return value.astimezone(timezone.utc)


class CommerceProductOfferCatalogRepository:
    """Immutable product/offer revisions with tenant-exact, as-of reads.

    The production schema is migration-owned and uses JSONB evidence refs so
    the reader remains forward compatible with EvidenceRef additions. Local
    storage mirrors the same tenant/revision keys for unit and developer use.
    """

    def __init__(self) -> None:
        self._local_products = _LOCAL_PRODUCTS
        self._local_offers = _LOCAL_OFFERS

    async def _pool(self) -> Any:
        if _LOCAL:
            return None
        return await get_pool()

    async def record_product(self, product: CommerceProductRecord) -> CommerceProductRecord:
        if not product.tenant_id.strip():
            raise ValueError("tenant_id is required")
        key = (product.tenant_id, product.product_id, product.source_revision_id)
        payload = product.model_dump(mode="json")
        pool = await self._pool()
        if pool is None:
            existing = self._local_products.get(key)
            if existing is not None and existing != payload:
                raise ValueError("product source revision id reused with different content")
            self._local_products[key] = payload
            return product

        async with pool.acquire() as conn:
            inserted = await conn.fetchrow(
                """
                INSERT INTO commerce_catalog_products (
                    tenant_id, product_id, revision_id, title, description,
                    lifecycle_state, valid_from, valid_to, observed_at,
                    source_provider, source_record_id, evidence_refs, data
                ) VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12::jsonb,$13::jsonb
                )
                ON CONFLICT (tenant_id, product_id, revision_id) DO NOTHING
                RETURNING revision_id
                """,
                product.tenant_id,
                product.product_id,
                product.source_revision_id,
                product.title,
                product.description,
                product.lifecycle_state,
                product.valid_from,
                product.valid_to,
                product.observed_at,
                product.source_provider,
                product.source_record_id,
                json.dumps([ref.model_dump(mode="json") for ref in product.evidence_refs]),
                json.dumps(payload),
            )
            if inserted is not None:
                return product
            existing = await conn.fetchrow(
                """SELECT data FROM commerce_catalog_products
                   WHERE tenant_id=$1 AND product_id=$2 AND revision_id=$3""",
                product.tenant_id,
                product.product_id,
                product.source_revision_id,
            )
        if existing is None:
            raise RuntimeError("product revision write did not persist")
        stored = _json_object(existing["data"])
        if stored != payload:
            raise ValueError("product source revision id reused with different content")
        return CommerceProductRecord.model_validate(stored)

    async def record_offer(self, offer: CommerceOfferRecord) -> CommerceOfferRecord:
        if not offer.tenant_id.strip():
            raise ValueError("tenant_id is required")
        product = await self.get_product(offer.tenant_id, offer.product_id)
        if product is None:
            raise ValueError("offer must reference an existing tenant product")
        key = (offer.tenant_id, offer.offer_id, offer.source_revision_id)
        payload = offer.model_dump(mode="json")
        pool = await self._pool()
        if pool is None:
            existing = self._local_offers.get(key)
            if existing is not None and existing != payload:
                raise ValueError("offer source revision id reused with different content")
            self._local_offers[key] = payload
            return offer

        async with pool.acquire() as conn:
            inserted = await conn.fetchrow(
                """
                INSERT INTO commerce_catalog_offers (
                    tenant_id, offer_id, revision_id, product_id, title,
                    description, lifecycle_state, valid_from, valid_to,
                    observed_at, source_provider, source_record_id,
                    evidence_refs, data
                ) VALUES (
                    $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13::jsonb,$14::jsonb
                )
                ON CONFLICT (tenant_id, offer_id, revision_id) DO NOTHING
                RETURNING revision_id
                """,
                offer.tenant_id,
                offer.offer_id,
                offer.source_revision_id,
                offer.product_id,
                offer.title,
                offer.description,
                offer.lifecycle_state,
                offer.valid_from,
                offer.valid_to,
                offer.observed_at,
                offer.source_provider,
                offer.source_record_id,
                json.dumps([ref.model_dump(mode="json") for ref in offer.evidence_refs]),
                json.dumps(payload),
            )
            if inserted is not None:
                return offer
            existing = await conn.fetchrow(
                """SELECT data FROM commerce_catalog_offers
                   WHERE tenant_id=$1 AND offer_id=$2 AND revision_id=$3""",
                offer.tenant_id,
                offer.offer_id,
                offer.source_revision_id,
            )
        if existing is None:
            raise RuntimeError("offer revision write did not persist")
        stored = _json_object(existing["data"])
        if stored != payload:
            raise ValueError("offer source revision id reused with different content")
        return CommerceOfferRecord.model_validate(stored)

    async def get_product(
        self, tenant_id: str, product_id: str, *, as_of: Optional[datetime] = None
    ) -> Optional[CommerceProductRecord]:
        if not tenant_id or not product_id:
            return None
        as_of = _normalize_as_of(as_of)
        pool = await self._pool()
        if pool is None:
            rows = [
                CommerceProductRecord.model_validate(raw)
                for (row_tenant, row_product, _), raw in self._local_products.items()
                if row_tenant == tenant_id and row_product == product_id
            ]
            if as_of is not None:
                rows = [row for row in rows if row.observed_at <= as_of]
            return _latest(rows, "source_revision_id")
        if as_of is None:
            query = """SELECT data FROM commerce_catalog_products
                       WHERE tenant_id=$1 AND product_id=$2
                       ORDER BY observed_at DESC, revision_id DESC LIMIT 1"""
            args: tuple[Any, ...] = (tenant_id, product_id)
        else:
            query = """SELECT data FROM commerce_catalog_products
                       WHERE tenant_id=$1 AND product_id=$2 AND observed_at <= $3
                       ORDER BY observed_at DESC, revision_id DESC LIMIT 1"""
            args = (tenant_id, product_id, as_of)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, *args)
        return CommerceProductRecord.model_validate(_json_object(row["data"])) if row else None

    async def get_offer(
        self, tenant_id: str, offer_id: str, *, as_of: Optional[datetime] = None
    ) -> Optional[CommerceOfferRecord]:
        if not tenant_id or not offer_id:
            return None
        as_of = _normalize_as_of(as_of)
        pool = await self._pool()
        if pool is None:
            rows = [
                CommerceOfferRecord.model_validate(raw)
                for (row_tenant, row_offer, _), raw in self._local_offers.items()
                if row_tenant == tenant_id and row_offer == offer_id
            ]
            if as_of is not None:
                rows = [row for row in rows if row.observed_at <= as_of]
            return _latest(rows, "source_revision_id")
        if as_of is None:
            query = """SELECT data FROM commerce_catalog_offers
                       WHERE tenant_id=$1 AND offer_id=$2
                       ORDER BY observed_at DESC, revision_id DESC LIMIT 1"""
            args: tuple[Any, ...] = (tenant_id, offer_id)
        else:
            query = """SELECT data FROM commerce_catalog_offers
                       WHERE tenant_id=$1 AND offer_id=$2 AND observed_at <= $3
                       ORDER BY observed_at DESC, revision_id DESC LIMIT 1"""
            args = (tenant_id, offer_id, as_of)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(query, *args)
        return CommerceOfferRecord.model_validate(_json_object(row["data"])) if row else None

    async def list_offers_for_product(
        self,
        tenant_id: str,
        product_id: str,
        *,
        as_of: Optional[datetime] = None,
        limit: int = 501,
    ) -> tuple[list[CommerceOfferRecord], bool]:
        """Return latest offer revision per ID, filtered by exact product link.

        The boolean indicates that the bounded query found more rows than the
        requested limit. Historical revisions are deduplicated before the
        product link filter so a moved offer cannot appear under its old item.
        """
        limit = min(max(int(limit), 1), 1001)
        as_of = _normalize_as_of(as_of)
        if not tenant_id or not product_id:
            return [], False
        pool = await self._pool()
        if pool is None:
            latest_by_id: dict[str, CommerceOfferRecord] = {}
            for (row_tenant, offer_id, _), raw in self._local_offers.items():
                if row_tenant != tenant_id:
                    continue
                row = CommerceOfferRecord.model_validate(raw)
                if as_of is not None and row.observed_at > as_of:
                    continue
                if _prefer_revision(row, latest_by_id.get(offer_id)):
                    latest_by_id[offer_id] = row
            matches = sorted(
                (row for row in latest_by_id.values() if row.product_id == product_id),
                key=lambda row: row.offer_id,
            )
            return matches[:limit], len(matches) > limit

        query = """
            WITH candidate_offers AS (
                SELECT DISTINCT offer_id
                FROM commerce_catalog_offers
                WHERE tenant_id=$1 AND product_id=$3
            ), latest AS (
                SELECT candidate.offer_id, revision.data, revision.product_id
                FROM candidate_offers AS candidate
                CROSS JOIN LATERAL (
                    SELECT data, product_id
                    FROM commerce_catalog_offers
                    WHERE tenant_id=$1 AND offer_id=candidate.offer_id
                      AND ($2::timestamptz IS NULL OR observed_at <= $2)
                    ORDER BY observed_at DESC, revision_id DESC
                    LIMIT 1
                ) AS revision
            )
            SELECT data FROM latest WHERE product_id=$3
            ORDER BY offer_id LIMIT $4
        """
        async with pool.acquire() as conn:
            rows = await conn.fetch(query, tenant_id, as_of, product_id, limit + 1)
        truncated = len(rows) > limit
        offers = [
            CommerceOfferRecord.model_validate(_json_object(row["data"])) for row in rows[:limit]
        ]
        return offers, truncated


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def _prefer_revision(candidate: _CatalogRecord, current: Optional[_CatalogRecord]) -> bool:
    if current is None:
        return True
    return (candidate.observed_at, candidate.model_dump().get("source_revision_id", "")) > (
        current.observed_at,
        current.model_dump().get("source_revision_id", ""),
    )


def _latest(rows: list[Any], revision_field: str) -> Any:
    if not rows:
        return None
    return max(rows, key=lambda row: (row.observed_at, getattr(row, revision_field)))


__all__ = [
    "CommerceCatalogLifecycle",
    "CommerceOfferRecord",
    "CommerceProductOfferCatalogRepository",
    "CommerceProductRecord",
]
