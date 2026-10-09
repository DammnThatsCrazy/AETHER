"""Tenant rights admission is required before provider raw retention and replay."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from config.settings import Environment, settings
from services.integrations.data_rights.models import DataRightsGrant, GrantStatus
from services.integrations.data_rights.service import data_rights_service
from services.provider_runtime.raw_store import RawProviderRecordStore
from services.provider_runtime.rights_admission import (
    PROVIDER_RAW_RIGHTS_METADATA_KEY,
    ProviderRawRightsAdmission,
    ProviderRawRightsDenied,
    provider_account_source_id,
)
from services.rights_authority.resolver import EffectiveRightsResolver
from repositories.lake import BronzeRepository
from repositories.repos import reset_in_memory_stores
from shared.integration_contracts.events import make_raw_record


class _DecisionRepository:
    def __init__(self):
        self.rows: dict[str, dict] = {}

    async def record(self, decision, *, identity_key=None):
        body = decision.model_dump(mode="json")
        body["identity_key"] = identity_key
        self.rows[body["decision_id"]] = body
        return body

    async def get(self, decision_id):
        return self.rows.get(decision_id)

    async def get_for_tenant(self, decision_id, *, tenant_id):
        row = self.rows.get(decision_id)
        return row if row and row.get("tenant_id") == tenant_id else None


def _grant(record, **changes) -> DataRightsGrant:
    values = {
        "data_rights_grant_id": "drg_provider_fixture",
        "tenant_id": record.tenant_id,
        "source_id": provider_account_source_id(record.connection_id, record.account_id),
        "connector_id": record.provider_identity,
        "connector_class": "tenant_byod_data",
        "data_category": "customer",
        "data_sensitivity": "sensitive_pii",
        "raw_data_owner": "tenant",
        "tenant_lake_allowed": True,
        "tenant_graph_allowed": True,
        "tenant_insights_allowed": True,
        "olympus_baseline_allowed": False,
        "cross_tenant_aggregate_allowed": False,
        "model_training_allowed": False,
        "commercial_reuse_allowed": False,
        "legal_basis": "contract",
        "granted_by_user_id": "tenant-admin",
        "granted_at": "2026-01-01T00:00:00+00:00",
        "status": GrantStatus.ACTIVE,
        "audit_event_id": "audit-provider-fixture",
    }
    values.update(changes)
    return DataRightsGrant(**values)


def _record():
    return make_raw_record(
        provider_identity="shopify.orders.catalog",
        provider_record_id="order-1",
        provider_record_type="order",
        tenant_id="tenant-1",
        connection_id="connection-1",
        account_id="shop-1",
        stream_id="orders",
        payload={"id": "order-1", "email": "customer@example.test"},
    )


def _admission(grant_getter):
    decisions = _DecisionRepository()

    async def grant_loader(tenant_id, source_id):
        grant = grant_getter()
        if grant is None or grant.tenant_id != tenant_id:
            return None
        # The resolver's grant loader contract is keyed by both tenant and source.
        if grant.source_id != source_id:
            return None
        return grant

    resolver = EffectiveRightsResolver(
        grant_loader=grant_loader,
        decision_repository=decisions,
    )

    async def grant_lookup(grant_ref, *, tenant_id):
        grant = grant_getter()
        return grant if (
            grant is not None
            and grant.data_rights_grant_id == grant_ref
            and grant.tenant_id == tenant_id
        ) else None

    return ProviderRawRightsAdmission(resolver=resolver, grant_lookup=grant_lookup), decisions


@pytest.mark.asyncio
async def test_active_tenant_byod_grant_admits_and_persists_verifiable_evidence():
    record = _record()
    grant = _grant(record)
    admission, decisions = _admission(lambda: grant)

    evidence = await admission.admit(record)
    metadata = dict(record.metadata)
    metadata[PROVIDER_RAW_RIGHTS_METADATA_KEY] = evidence.model_dump(mode="json")
    persisted = record.model_copy(update={"metadata": metadata})
    await admission.verify_persisted(persisted, current_admission=evidence)

    assert evidence.tenant_id == record.tenant_id
    assert evidence.source_id == grant.source_id
    assert evidence.source_grant_ref == grant.data_rights_grant_id
    assert evidence.rights_decision_ref in decisions.rows
    assert decisions.rows[evidence.rights_decision_ref]["allowed"] is True


@pytest.mark.asyncio
async def test_default_raw_store_uses_canonical_global_rights_authorities(monkeypatch):
    record = _record()
    grant = _grant(record)
    monkeypatch.setattr(settings, "env", Environment.LOCAL)
    monkeypatch.setattr(
        data_rights_service._repository,
        "_local_grants",
        {grant.data_rights_grant_id: grant},
    )
    reset_in_memory_stores()
    repository = BronzeRepository("test_global_rights_provider_records")

    (persisted, was_new), = await RawProviderRecordStore(repository=repository).ingest([record])

    assert was_new is True
    assert persisted.metadata[PROVIDER_RAW_RIGHTS_METADATA_KEY]["source_grant_ref"] == (
        grant.data_rights_grant_id
    )
    rows = await repository.find_many(filters={"tenant_id": record.tenant_id}, limit=10)
    assert len(rows) == 1
    assert rows[0]["provenance_status"] == "valid"


@pytest.mark.asyncio
async def test_absent_grant_denies_before_raw_admission():
    admission, _ = _admission(lambda: None)

    with pytest.raises(ProviderRawRightsDenied):
        await admission.admit(_record())


@pytest.mark.asyncio
async def test_admission_passes_record_tenant_to_grant_lookup():
    record = _record()
    grant = _grant(record)
    seen_tenants = []
    decisions = _DecisionRepository()

    async def grant_loader(tenant_id, source_id):
        return grant if (tenant_id, source_id) == (grant.tenant_id, grant.source_id) else None

    resolver = EffectiveRightsResolver(
        grant_loader=grant_loader, decision_repository=decisions,
    )

    async def scoped_lookup(grant_ref, *, tenant_id):
        seen_tenants.append(tenant_id)
        return grant if grant_ref == grant.data_rights_grant_id and tenant_id == "tenant-1" else None

    admission = ProviderRawRightsAdmission(resolver=resolver, grant_lookup=scoped_lookup)
    await admission.admit(record)
    assert seen_tenants == [record.tenant_id]


@pytest.mark.asyncio
async def test_cross_tenant_grant_lookup_denies_even_when_reference_matches():
    record = _record()
    authorized_grant = _grant(record)
    foreign = _grant(record, tenant_id="tenant-2")
    decisions = _DecisionRepository()

    async def grant_loader(tenant_id, source_id):
        return authorized_grant if (
            tenant_id == authorized_grant.tenant_id
            and source_id == authorized_grant.source_id
        ) else None

    resolver = EffectiveRightsResolver(
        grant_loader=grant_loader, decision_repository=decisions,
    )

    async def cross_tenant_lookup(grant_ref, *, tenant_id):
        assert tenant_id == record.tenant_id
        return foreign if grant_ref == foreign.data_rights_grant_id else None

    admission = ProviderRawRightsAdmission(
        resolver=resolver, grant_lookup=cross_tenant_lookup,
    )

    with pytest.raises(ProviderRawRightsDenied):
        await admission.admit(record)


@pytest.mark.asyncio
async def test_byok_or_mismatched_source_grant_cannot_admit_tenant_raw_data():
    record = _record()
    byok_grant = _grant(record, connector_class="byok_gateway")
    byok_admission, _ = _admission(lambda: byok_grant)
    with pytest.raises(ProviderRawRightsDenied):
        await byok_admission.admit(record)

    mismatched_grant = _grant(
        record,
        source_id=provider_account_source_id(record.connection_id, "another-shop"),
    )
    mismatched_admission, _ = _admission(lambda: mismatched_grant)
    with pytest.raises(ProviderRawRightsDenied):
        await mismatched_admission.admit(record)


@pytest.mark.asyncio
async def test_expired_or_revoked_grant_denies_admission():
    record = _record()
    revoked = _grant(
        record,
        status=GrantStatus.REVOKED,
        revoked_at=datetime.now(timezone.utc).isoformat(),
    )
    admission, _ = _admission(lambda: revoked)

    with pytest.raises(ProviderRawRightsDenied):
        await admission.admit(record)

    expired = _grant(record, expires_at="2020-01-01T00:00:00+00:00")
    expired_admission, _ = _admission(lambda: expired)
    with pytest.raises(ProviderRawRightsDenied):
        await expired_admission.admit(record)


@pytest.mark.asyncio
async def test_replay_rechecks_current_rights_after_original_allow():
    record = _record()
    current = _grant(record)
    admission, _ = _admission(lambda: current)
    evidence = await admission.admit(record)
    metadata = dict(record.metadata)
    metadata[PROVIDER_RAW_RIGHTS_METADATA_KEY] = evidence.model_dump(mode="json")
    persisted = record.model_copy(update={"metadata": metadata})
    await admission.authorize_replay(persisted)

    current = current.model_copy(
        update={
            "status": GrantStatus.REVOKED,
            "revoked_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    with pytest.raises(ProviderRawRightsDenied):
        await admission.authorize_replay(persisted)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("requested_use", "tenant_graph"),
        ("purpose", "another_purpose"),
        ("destination", "another_destination"),
        ("evaluated_at", "2025-01-01T00:00:00+00:00"),
    ],
)
async def test_replay_rejects_rights_evidence_not_bound_to_recorded_decision(field, value):
    record = _record()
    grant = _grant(record)
    admission, _ = _admission(lambda: grant)
    evidence = await admission.admit(record)
    changed = evidence.model_copy(update={field: value})
    metadata = dict(record.metadata)
    metadata[PROVIDER_RAW_RIGHTS_METADATA_KEY] = changed.model_dump(mode="json")
    persisted = record.model_copy(update={"metadata": metadata})

    with pytest.raises(ProviderRawRightsDenied):
        await admission.authorize_replay(persisted)


@pytest.mark.asyncio
async def test_default_admission_fails_closed_in_production_without_durable_grant_store(
    monkeypatch,
):
    monkeypatch.setattr(settings, "env", Environment.PRODUCTION)

    with pytest.raises(ProviderRawRightsDenied):
        await ProviderRawRightsAdmission().admit(_record())


@pytest.mark.asyncio
async def test_injected_adapters_cannot_bypass_production_durable_store_gate(monkeypatch):
    record = _record()
    grant = _grant(record)
    admission, _ = _admission(lambda: grant)
    monkeypatch.setattr(settings, "env", Environment.STAGING)

    with pytest.raises(ProviderRawRightsDenied):
        await admission.admit(record)
