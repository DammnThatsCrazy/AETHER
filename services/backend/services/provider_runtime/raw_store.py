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


_ALLOWED_LICENSE_STATUSES = {"valid", "public_api", "open_license", "enterprise_contract"}
_ALLOWED_TERMS_STATUSES = {
    "approved", "public_api", "open_license", "enterprise_contract", "valid",
}
_ALLOWED_COMMERCIAL_USE_STATUSES = {"approved"}
_DENIED_RIGHTS_STATUSES = {"denied", "revoked", "blocked", "rejected", "disallowed"}


def _bronze_admission(record: dict) -> tuple[bool, str]:
    """Return whether this durable Bronze row may enter provider processing.

    Bronze is the authority for provenance and quarantine. The explicit checks
    also defend against inconsistent rows (for example, a manually supplied
    ``valid`` provenance paired with a revoked license or denied rights).
    Missing values never imply permission.
    """
    if record.get("quarantine_status") != "not_quarantined":
        return False, "bronze_quarantined"
    if record.get("provenance_status") != "valid":
        return False, "provenance_not_valid"
    if record.get("license_status") not in _ALLOWED_LICENSE_STATUSES:
        return False, "license_not_verified"
    if record.get("terms_status") not in _ALLOWED_TERMS_STATUSES:
        return False, "terms_not_approved"
    if record.get("commercial_use_status") not in _ALLOWED_COMMERCIAL_USE_STATUSES:
        return False, "commercial_use_not_approved"
    for field in ("license_status", "terms_status", "commercial_use_status"):
        value = str(record.get(field, "unknown")).strip().lower()
        if value in _DENIED_RIGHTS_STATUSES:
            return False, "rights_denied"
    return True, "admitted"


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
        outcomes = await self.ingest_with_admission(records, tenant_id=tenant_id)
        return [(record, was_new) for record, was_new, _admitted, _reason in outcomes]

    async def ingest_with_admission(
        self,
        records: Iterable[RawProviderRecord],
        *,
        tenant_id: str | None = None,
    ) -> list[tuple[RawProviderRecord, bool, bool, str]]:
        """Persist records and return the actual Bronze admission decision.

        The first two fields retain ``ingest``'s outcome semantics. ``admitted``
        is derived from the persisted row returned by Bronze, including on
        dedupe, so callers must not infer permission from provider metadata.
        """
        outcomes: list[tuple[RawProviderRecord, bool, bool, str]] = []
        for record in records:
            effective_tenant = tenant_id if tenant_id is not None else record.tenant_id
            source = record.provider_identity
            bronze_record, was_new = await self._repository.ingest(
                source=source,
                source_tag=f"provider:{source}:{effective_tenant}",
                provider_record_id=record.provider_record_id,
                payload=record.model_dump(),
                schema_version=record.schema_version,  # envelope version — see module docstring
                entity_id=record.provider_record_id,
                entity_type=record.provider_record_type or "",
                tenant_id=effective_tenant,
            )
            admitted, reason = _bronze_admission(bronze_record)
            outcomes.append((record, was_new, admitted, reason))
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
