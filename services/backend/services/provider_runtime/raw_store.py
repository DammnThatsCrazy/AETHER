"""Raw provider record store — rights-gated raw-before-canonical persistence.

Every :class:`~shared.integration_contracts.events.RawProviderRecord` an
acquisition adapter produces must first pass the canonical tenant rights
authority. Only then does it land in Bronze *before* normalization runs.
The store is idempotent on the Bronze dedup key
``tenant_id:source:bronze_provider_record_id:schema_version`` (the
:class:`~repositories.lake.BronzeRepository` contract), so re-ingesting the same
raw record is a no-op returning ``was_new=False``.

For revision-aware records, ``bronze_provider_record_id`` is a bounded digest
of the verified source account, object, and revision. Historical v1 records
keep the native ``provider_record_id`` key. A duplicate returns the already
persisted raw envelope and its original ``record_id`` for stable lineage.

``source`` is the record's ``provider_identity`` (the full
``family.product.capability``), which keeps records from different capabilities
of the same provider from colliding on the same ``provider_record_id``. The full
raw record (``model_dump()``) is preserved in Bronze ``payload`` so lineage and
audit survive; ``provider_record_type`` is projected onto Bronze ``entity_type``
so it is filterable/countable without touching lake.py.

Bronze ``schema_version`` is the record's *envelope* ``schema_version`` (default
``"1"``), NOT the optional ``payload_schema_version`` (a provider-payload format
tag). Using the envelope version keeps the Bronze dedup key identical to
:attr:`RawProviderRecord.idempotency_key` — both use the Bronze provider record
key — so the store
dedupes exactly what the record itself considers one record, regardless of
provider payload-format churn.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Optional

from shared.integration_contracts.events import RawProviderRecord
from shared.integration_contracts.events import verify_checksum

# Module-level import is safe (lake.py constructs only in-memory singletons).
from repositories.lake import BronzeRepository
from services.provider_runtime.rights_admission import ProviderRawRightsAdmission


class ProviderRawRecordQuarantined(RuntimeError):
    """Persisted provider raw evidence is not admitted for normalization.

    The message intentionally contains no provider payload, record identifier,
    tenant identifier, or other source data; callers can safely surface only
    the exception type as a denial reason.
    """

    def __init__(self) -> None:
        super().__init__("provider raw record failed Bronze provenance admission")


class RawProviderRecordStore:
    """Persists RawProviderRecord to Bronze before any normalization."""

    def __init__(self, repository=None, *, rights_admission=None) -> None:
        # Default: a fresh BronzeRepository over the provider_records domain.
        self._repository = repository if repository is not None else BronzeRepository("provider_records")
        self._rights_admission = (
            rights_admission if rights_admission is not None else ProviderRawRightsAdmission()
        )

    async def ingest(
        self,
        records: Iterable[RawProviderRecord],
        *,
        tenant_id: str | None = None,
    ) -> list[tuple[RawProviderRecord, bool]]:
        """Ingest raw records; returns ``(record, was_new)`` per record.

        ``was_new`` is True only for a fresh Bronze insert; duplicates per the
        Bronze dedup key return the previously persisted record. ``tenant_id``
        overrides the record's own ``tenant_id`` before persistence and hashing.
        Tenant rights admission is the single gate: a denied record raises and
        nothing is retained.
        """
        outcomes: list[tuple[RawProviderRecord, bool]] = []
        for record in records:
            effective_tenant = tenant_id if tenant_id is not None else record.tenant_id
            if not effective_tenant:
                raise ValueError("tenant_id is required for provider raw ingestion")
            if effective_tenant != record.tenant_id:
                record = record.model_copy(update={"tenant_id": effective_tenant})
            # Integrity is checked before the first durable write. A corrupt
            # envelope must never be marked valid in Bronze and rejected only
            # after its full source payload has already been retained.
            if not verify_checksum(record):
                raise ValueError("provider raw record checksum is invalid")
            admission = await self._rights_admission.admit(record)
            if admission.tenant_id != effective_tenant:
                raise ProviderRawRecordQuarantined()
            metadata = dict(record.metadata or {})
            metadata["aether_rights_admission"] = admission.model_dump(mode="json")
            record = record.model_copy(update={"metadata": metadata})
            source = record.provider_identity
            try:
                stored, was_new = await self._repository.ingest(
                    source=source,
                    source_tag=f"provider:{source}:{effective_tenant}",
                    provider_record_id=record.bronze_provider_record_id,
                    payload=record.model_dump(),
                    schema_version=record.schema_version,  # envelope version
                    entity_id=record.provider_record_id,
                    entity_type=record.provider_record_type or "",
                    tenant_id=effective_tenant,
                    provenance_status="valid",
                    license_status="tenant_rights_granted",
                    terms_status="active_grant",
                )
            except Exception as exc:
                # Two workers can pass BronzeRepository's read-before-insert
                # simultaneously. The v2 partial unique index rejects the
                # loser; read the winner and return its lineage. Never treat an
                # unrelated database error as a duplicate.
                if (
                    record.schema_version != "2"
                    or getattr(exc, "constraint_name", None)
                    != "ux_bronze_provider_raw_v2_revision"
                ):
                    raise
                matches = await self._repository.find_many(
                    filters={
                        "tenant_id": effective_tenant,
                        "idempotency_key": record.idempotency_key,
                    },
                    limit=1,
                )
                if not matches:
                    raise
                stored, was_new = matches[0], False
            # Bronze is the authority for persisted provenance. Never allow
            # adapter metadata or the in-memory RawProviderRecord to override
            # this result. Missing or inconsistent fields fail closed too.
            if (
                not isinstance(stored, dict)
                or stored.get("quarantine_status") != "not_quarantined"
                or stored.get("provenance_status") != "valid"
            ):
                raise ProviderRawRecordQuarantined()
            persisted_payload = stored.get("payload") if isinstance(stored, dict) else None
            if not isinstance(persisted_payload, dict):
                raise ValueError("Bronze did not return a persisted provider raw envelope")
            persisted_record = RawProviderRecord.model_validate(persisted_payload)
            if (
                persisted_record.tenant_id != effective_tenant
                or persisted_record.provider_identity != source
                or persisted_record.bronze_provider_record_id
                != record.bronze_provider_record_id
            ):
                raise ValueError("Bronze returned a raw record outside the requested source revision")
            if not verify_checksum(persisted_record):
                raise ValueError("Bronze returned a raw record with an invalid checksum")
            await self._rights_admission.verify_persisted(
                persisted_record,
                current_admission=admission,
            )
            outcomes.append((persisted_record, was_new))
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


__all__ = ["ProviderRawRecordQuarantined", "RawProviderRecordStore"]
