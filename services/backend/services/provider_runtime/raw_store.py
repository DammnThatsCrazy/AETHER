"""Raw provider record store — raw-before-canonical Bronze persistence.

Every :class:`~shared.integration_contracts.events.RawProviderRecord` an
acquisition adapter produces lands in Bronze *before* any normalization runs.
The store is idempotent on the Bronze dedup key
``tenant_id:source:provider_record_id:schema_version`` (the
:class:`~repositories.lake.BronzeRepository` contract), so re-ingesting the same
raw record is a no-op returning ``was_new=False``.

``source`` is the record's ``provider_identity`` (the full
``family.product.capability``), which keeps records from different capabilities
of the same provider from colliding on the same ``provider_record_id``. The full
raw record (``model_dump()``) is preserved in Bronze ``payload`` so lineage and
audit survive; ``provider_record_type`` is projected onto Bronze ``entity_type``
so it is filterable/countable without touching lake.py.

Bronze ``schema_version`` is the record's *envelope* ``schema_version`` (default
``"1"``), NOT the optional ``payload_schema_version`` (a provider-payload format
tag). Using the envelope version keeps the Bronze dedup key identical to
:attr:`RawProviderRecord.idempotency_key` — both are
``tenant:provider_identity:provider_record_id:schema_version`` — so the store
dedupes exactly what the record itself considers one record, regardless of
provider payload-format churn.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Optional

from shared.integration_contracts.events import RawProviderRecord

# Module-level import is safe (lake.py constructs only in-memory singletons).
from repositories.lake import BronzeRepository


class RawProviderRecordStore:
    """Persists RawProviderRecord to Bronze before any normalization."""

    def __init__(self, repository=None) -> None:
        # Default: a fresh BronzeRepository over the provider_records domain.
        self._repository = repository if repository is not None else BronzeRepository("provider_records")

    async def ingest(
        self,
        records: Iterable[RawProviderRecord],
        *,
        tenant_id: str | None = None,
    ) -> list[tuple[RawProviderRecord, bool]]:
        """Ingest raw records; returns ``(record, was_new)`` per record.

        ``was_new`` is True only for a fresh Bronze insert; duplicates per the
        Bronze dedup key return ``(record, False)``. ``tenant_id`` overrides the
        record's own ``tenant_id`` when supplied.
        """
        outcomes: list[tuple[RawProviderRecord, bool]] = []
        for record in records:
            effective_tenant = tenant_id if tenant_id is not None else record.tenant_id
            source = record.provider_identity
            _, was_new = await self._repository.ingest(
                source=source,
                source_tag=f"provider:{source}:{effective_tenant}",
                provider_record_id=record.provider_record_id,
                payload=record.model_dump(),
                schema_version=record.schema_version,  # envelope version — see module docstring
                entity_id=record.provider_record_id,
                entity_type=record.provider_record_type or "",
                tenant_id=effective_tenant,
            )
            outcomes.append((record, was_new))
        return outcomes

    async def count(
        self,
        *,
        tenant_id: str,
        provider_identity: str,
        provider_record_type: str | None = None,
    ) -> int:
        """Count raw records for a tenant/provider (optionally by record type).

        Filters on Bronze ``source`` (= ``provider_identity``) and — when given —
        Bronze ``entity_type`` (= ``provider_record_type``), tenant-scoped.
        """
        filters: dict[str, str] = {
            "tenant_id": tenant_id,
            "source": provider_identity,
        }
        if provider_record_type:
            filters["entity_type"] = provider_record_type
        return await self._repository.count(filters=filters)


__all__ = ["RawProviderRecordStore"]
