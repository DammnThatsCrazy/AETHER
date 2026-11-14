"""Rights admission for raw provider records.

Provider authentication proves who sent a record; it does not authorize Aether
to retain or use that record. This module binds raw persistence and replay to
the canonical Effective Rights Resolver and the one active grant governing the
record's source scope. The grant's rights-source class picks the retention use;
its source relationship can only deny, never allow.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable, Iterable, Optional

from pydantic import BaseModel, ConfigDict, Field

from shared.integration_contracts.events import RawProviderRecord
from shared.integration_contracts.source_relationship import (
    OLYMPUS_SOURCE_TENANT_ID,
    UNCLASSIFIED,
    relationship_consistent,
)
from shared.logger.logger import metrics

PROVIDER_RAW_RIGHTS_METADATA_KEY = "aether_rights_admission"
PROVIDER_RAW_RIGHTS_PURPOSE = "provider_raw_ingestion"
PROVIDER_RAW_RIGHTS_USE = "tenant_lake"
PROVIDER_RAW_RIGHTS_DESTINATION = "tenant_lake"

# Raw retention uses requested_use == destination; the grant flag is f"{use}_allowed".
_RAW_RETENTION_USE_BY_CLASS = {
    "tenant_byod_data": "tenant_lake",
    "olympus_provider": "olympus_baseline",
}


class ProviderRawRightsDenied(RuntimeError):
    """A provider record has no current storage authorization for its rights-source class."""

    def __init__(self) -> None:
        super().__init__("provider raw record has no current rights admission")


class ProviderRawRightsEvidence(BaseModel):
    """Immutable reference to the grant and decision that admitted one record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_grant_ref: str = Field(min_length=1)
    rights_decision_ref: str = Field(min_length=1)
    decision_identity: str = Field(min_length=1)
    requested_use: str = PROVIDER_RAW_RIGHTS_USE
    purpose: str = PROVIDER_RAW_RIGHTS_PURPOSE
    destination: str = PROVIDER_RAW_RIGHTS_DESTINATION
    policy_version: str = Field(min_length=1)
    evaluated_at: str = Field(min_length=1)
    source_relationship: str = UNCLASSIFIED


def provider_account_source_id(connection_id: str, account_id: str) -> str:
    """Return the stable source scope used by DataRightsGrant for one account."""
    connection = (connection_id or "").strip()
    account = (account_id or "").strip()
    if not connection or not account:
        raise ProviderRawRightsDenied()
    return f"provider-account:{connection}:{account}"


def provider_stream_source_id(connection_id: str, stream_id: str) -> str:
    """Return the stable source scope for one declared accountless stream."""
    connection = (connection_id or "").strip()
    stream = (stream_id or "").strip()
    if not connection or not stream:
        raise ProviderRawRightsDenied()
    return f"provider-stream:{connection}:{stream}"


def _installed_streams(provider_identity: str) -> Iterable[Any]:
    from connectors.provider_runtime.registry import provider_registry

    return provider_registry.streams_for(provider_identity)


def provider_source_id(
    record: RawProviderRecord,
    *,
    stream_lookup: Optional[Callable[[str], Iterable[Any]]] = None,
) -> str:
    """Account scope when the record names an account, else a manifest-declared stream.

    The stream id must be declared by the capability manifest; a record-supplied
    stream id alone never creates a scope, and there is no connection-wide scope.
    """
    if (record.account_id or "").strip():
        return provider_account_source_id(record.connection_id, record.account_id)
    stream_id = (record.stream_id or "").strip()
    if not stream_id:
        raise ProviderRawRightsDenied()
    try:
        declared = {
            str(descriptor.stream_id)
            for descriptor in (stream_lookup or _installed_streams)(record.provider_identity)
        }
    except Exception:
        raise ProviderRawRightsDenied() from None
    if stream_id not in declared:
        raise ProviderRawRightsDenied()
    return provider_stream_source_id(record.connection_id, stream_id)


def raw_retention_use(grant: Any) -> Optional[str]:
    """Raw-retention use for a grant's rights-source class; None means no retention."""
    connector_class = str(getattr(grant, "connector_class", "") or "")
    olympus_scope = str(getattr(grant, "tenant_id", "") or "") == OLYMPUS_SOURCE_TENANT_ID
    if connector_class == "partner_feed":
        return "olympus_baseline" if olympus_scope else "tenant_lake"
    if connector_class == "olympus_provider" and not olympus_scope:
        return None
    return _RAW_RETENTION_USE_BY_CLASS.get(connector_class)


def _request_for_record(record: RawProviderRecord, source_id: str, requested_use: str):
    from tenancy.rights_authority.contracts import RightsDecisionRequest
    from tenancy.rights_authority.resolver import decision_identity

    if (
        not record.tenant_id
        or not record.provider_identity
        or not record.idempotency_key
        or not requested_use
    ):
        raise ProviderRawRightsDenied()
    request = RightsDecisionRequest(
        tenant_id=record.tenant_id,
        source_id=source_id,
        artifact_ref=record.idempotency_key,
        artifact_class="provider_raw_record",
        actor="provider_runtime",
        actor_role="system",
        requested_use=requested_use,
        purpose=PROVIDER_RAW_RIGHTS_PURPOSE,
        destination=requested_use,
    )
    identity = decision_identity(
        tenant_id=request.tenant_id,
        actor=request.actor,
        purpose=request.purpose,
        artifact=request.artifact_ref,
        requested_use=request.requested_use,
        destination=request.destination,
        source_id=request.source_id,
        subject_ref=request.subject_ref or "",
    )
    return request, identity


def _grant_admits(grant: Any, record: RawProviderRecord, source_id: str, requested_use: str) -> bool:
    status = getattr(grant, "status", None)
    status_value = getattr(status, "value", status)
    return bool(
        grant is not None
        and str(getattr(grant, "tenant_id", "") or "") == record.tenant_id
        and str(getattr(grant, "source_id", "") or "") == source_id
        and str(getattr(grant, "connector_id", "") or "") == record.provider_identity
        and raw_retention_use(grant) == requested_use
        and relationship_consistent(
            getattr(grant, "source_relationship", None), getattr(grant, "connector_class", None),
        )
        and bool(getattr(grant, f"{requested_use}_allowed", False))
        and status_value == "active"
        and getattr(grant, "revoked_at", None) is None
    )


class ProviderRawRightsAdmission:
    """Resolve, record, and re-check raw provider storage rights.

    The production default uses ``effective_rights_resolver``. Tests or a host
    application may inject the same canonical resolver and grant lookup; this
    seam never accepts a caller-provided allow boolean or provider metadata.
    """

    def __init__(
        self, *, resolver: Any = None, grant_lookup: Any = None, grant_service: Any = None,
        stream_lookup: Optional[Callable[[str], Iterable[Any]]] = None,
    ) -> None:
        self._resolver = resolver
        self._grant_lookup = grant_lookup
        # Defaults to the process-wide data-rights service; tests inject their own.
        self._grant_service = grant_service
        self._stream_lookup = stream_lookup

    def _service(self) -> Any:
        if self._grant_service is not None:
            return self._grant_service
        from connectors.integrations.data_rights.service import data_rights_service

        return data_rights_service

    async def _authority(self) -> tuple[Any, Any]:
        from config.settings import Environment, settings

        data_rights_service = self._service()

        # This deployment invariant applies even when a host injects resolver
        # adapters: production must use the canonical durable grant service.
        if (
            settings.env in (Environment.STAGING, Environment.PRODUCTION)
            and not await data_rights_service.is_durable()
        ):
            self._deny("grant_store_not_durable")

        resolver = self._resolver
        grant_lookup = self._grant_lookup
        if resolver is None or grant_lookup is None:
            from tenancy.rights_authority.resolver import effective_rights_resolver
            resolver = resolver or effective_rights_resolver
            grant_lookup = grant_lookup or data_rights_service.get_grant
        return resolver, grant_lookup

    @staticmethod
    def _deny(reason: str) -> None:
        metrics.increment("provider_raw_rights_denials_total", labels={"reason": reason})
        raise ProviderRawRightsDenied()

    def _source_id(self, record: RawProviderRecord) -> str:
        return provider_source_id(record, stream_lookup=self._stream_lookup)

    async def admit(self, record: RawProviderRecord) -> ProviderRawRightsEvidence:
        """Resolve a fresh allow decision before any full raw payload is written."""
        try:
            source_id = self._source_id(record)
            resolver, grant_lookup = await self._authority()
            governing = await resolver.governing_grant(record.tenant_id, source_id)
        except ProviderRawRightsDenied:
            raise
        except Exception:
            self._deny("authority_unavailable")
        if governing is None:
            self._deny("no_grant")
        requested_use = raw_retention_use(governing)
        if requested_use is None:
            self._deny("no_raw_retention_use")
        if not relationship_consistent(
            getattr(governing, "source_relationship", None),
            getattr(governing, "connector_class", None),
        ):
            self._deny("relationship_mismatch")

        try:
            request, identity = _request_for_record(record, source_id, requested_use)
            decision = await resolver.resolve_request(request)
        except ProviderRawRightsDenied:
            raise
        except Exception:
            self._deny("authority_unavailable")

        grant_refs = list(getattr(decision, "source_grant_refs", []) or [])
        if (
            not bool(getattr(decision, "allowed", False))
            or str(getattr(decision, "tenant_id", "") or "") != record.tenant_id
            or str(getattr(decision, "policy_version", "") or "") == ""
            or grant_refs != [governing.data_rights_grant_id]
        ):
            self._deny("rights_denied")
        grant_ref = str(grant_refs[0])
        try:
            grant = await grant_lookup(grant_ref, tenant_id=record.tenant_id)
        except Exception:
            self._deny("grant_lookup_failed")
        if not _grant_admits(grant, record, source_id, requested_use):
            self._deny("grant_scope_mismatch")

        return ProviderRawRightsEvidence(
            tenant_id=record.tenant_id,
            source_id=source_id,
            source_grant_ref=grant_ref,
            rights_decision_ref=str(getattr(decision, "decision_id", "") or ""),
            decision_identity=identity,
            requested_use=request.requested_use,
            purpose=request.purpose,
            destination=request.destination,
            policy_version=str(getattr(decision, "policy_version", "") or ""),
            evaluated_at=str(getattr(decision, "evaluated_at", "") or ""),
            source_relationship=str(getattr(grant, "source_relationship", "") or UNCLASSIFIED),
        )

    @asynccontextmanager
    async def hold_grant(
        self,
        record: RawProviderRecord,
        admission: ProviderRawRightsEvidence,
    ) -> AsyncIterator[None]:
        """Keep the admitting grant unrevoked while the raw record is written.

        ``admit`` decides at one instant; the Bronze write happens later. A
        revocation could commit in between and leave a record retained after
        its grant was revoked. This takes the grant's shared hold (revocation
        takes the same lock exclusively), then re-reads the grant under it:
        a revocation that already committed denies the write, and one that
        arrives later waits until the write has committed.
        """
        service = self._service()
        grant_lookup = self._grant_lookup or service.get_grant
        async with service.hold_grant_unrevoked(
            admission.source_grant_ref, tenant_id=record.tenant_id,
        ):
            try:
                grant = await grant_lookup(
                    admission.source_grant_ref, tenant_id=record.tenant_id,
                )
            except Exception:
                self._deny("grant_lookup_failed")
            if not _grant_admits(grant, record, admission.source_id, admission.requested_use):
                self._deny("grant_revoked_before_write")
            yield

    async def _stored_admission(
        self, record: RawProviderRecord,
    ) -> ProviderRawRightsEvidence:
        raw_evidence = (record.metadata or {}).get(PROVIDER_RAW_RIGHTS_METADATA_KEY)
        try:
            stored = ProviderRawRightsEvidence.model_validate(raw_evidence)
            request, identity = _request_for_record(
                record, self._source_id(record), stored.requested_use,
            )
            resolver, _grant_lookup = await self._authority()
            repo = getattr(resolver, "_repo", None)
            decision_row = await repo.get_for_tenant(
                stored.rights_decision_ref, tenant_id=record.tenant_id,
            )
        except ProviderRawRightsDenied:
            raise
        except Exception:
            self._deny("admission_evidence_invalid")
        if (
            stored.tenant_id != record.tenant_id
            or stored.source_id != request.source_id
            or stored.decision_identity != identity
            or stored.destination != request.destination
            or stored.purpose != request.purpose
            or not isinstance(decision_row, dict)
            or str(decision_row.get("decision_id", "")) != stored.rights_decision_ref
            or decision_row.get("identity_key") != identity
            or decision_row.get("tenant_id") != record.tenant_id
            or decision_row.get("allowed") is not True
            or decision_row.get("policy_version") != stored.policy_version
            or decision_row.get("evaluated_at") != stored.evaluated_at
            or decision_row.get("source_grant_refs") != [stored.source_grant_ref]
        ):
            self._deny("admission_evidence_mismatch")
        return stored

    async def verify_persisted(
        self,
        record: RawProviderRecord,
        *,
        current_admission: ProviderRawRightsEvidence,
    ) -> None:
        """Validate stored evidence against the append-only decision authority."""
        stored = await self._stored_admission(record)
        if (
            stored.source_grant_ref != current_admission.source_grant_ref
            or stored.policy_version != current_admission.policy_version
            or stored.requested_use != current_admission.requested_use
        ):
            self._deny("admission_evidence_mismatch")

    async def authorize_replay(self, record: RawProviderRecord) -> None:
        """Require the original allow record and a fresh, same-grant, same-use allow."""
        stored = await self._stored_admission(record)
        current = await self.admit(record)
        if current.source_grant_ref != stored.source_grant_ref:
            self._deny("grant_changed")
        if current.requested_use != stored.requested_use:
            self._deny("retention_use_changed")


__all__ = [
    "PROVIDER_RAW_RIGHTS_DESTINATION",
    "PROVIDER_RAW_RIGHTS_METADATA_KEY",
    "PROVIDER_RAW_RIGHTS_PURPOSE",
    "PROVIDER_RAW_RIGHTS_USE",
    "ProviderRawRightsAdmission",
    "ProviderRawRightsDenied",
    "ProviderRawRightsEvidence",
    "provider_account_source_id",
    "provider_source_id",
    "provider_stream_source_id",
    "raw_retention_use",
]
