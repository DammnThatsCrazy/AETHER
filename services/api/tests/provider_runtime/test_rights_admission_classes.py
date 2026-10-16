"""Provider raw admission across rights-source classes (fail closed)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from config.settings import Environment, settings
from connectors.integrations.data_rights.models import DataRightsGrant, GrantStatus
from connectors.provider_runtime import rights_admission as rights_admission_module
from connectors.provider_runtime.rights_admission import (
    PROVIDER_RAW_RIGHTS_METADATA_KEY,
    ProviderRawRightsAdmission,
    ProviderRawRightsDenied,
    provider_account_source_id,
    provider_stream_source_id,
    raw_retention_use,
)
from shared.integration_contracts.events import make_raw_record
from shared.integration_contracts.source_relationship import OLYMPUS_SOURCE_TENANT_ID
from tenancy.rights_authority.resolver import EffectiveRightsResolver


class _Decisions:
    def __init__(self):
        self.rows = {}

    async def record(self, decision, *, identity_key=None):
        body = decision.model_dump(mode="json")
        body["identity_key"] = identity_key
        self.rows[body["decision_id"]] = body
        return body

    async def get_for_tenant(self, decision_id, *, tenant_id):
        row = self.rows.get(decision_id)
        return row if row and row.get("tenant_id") == tenant_id else None

    async def find_by_identity(self, tenant_id, identity_key, limit=1):
        return None


def _record(tenant="tenant-1", provider="shopify.admin.orders_read", account="shop-1", stream="orders"):
    return make_raw_record(
        provider_identity=provider, provider_record_id="r-1", provider_record_type="order",
        tenant_id=tenant, connection_id="conn_1", account_id=account, stream_id=stream,
        payload={"id": "r-1"},
    )


def _grant(record, source_id=None, **changes):
    values = dict(
        data_rights_grant_id="drg_fixture", tenant_id=record.tenant_id,
        source_id=source_id or provider_account_source_id(record.connection_id, record.account_id),
        connector_id=record.provider_identity, connector_class="tenant_byod_data",
        data_category="commerce", data_sensitivity="internal", raw_data_owner="tenant",
        source_relationship="organization_system", tenant_lake_allowed=True,
        legal_basis="contract", granted_by_user_id="admin", granted_at="2026-01-01T00:00:00+00:00",
        audit_event_id="audit_fixture", status=GrantStatus.ACTIVE,
    )
    values.update(changes)
    return DataRightsGrant(**values)


def _admission(grant, *, streams=("orders",)):
    decisions = _Decisions()

    async def loader(tenant_id, source_id):
        if grant is None or grant.tenant_id != tenant_id or grant.source_id != source_id:
            return None
        return grant

    async def lookup(ref, *, tenant_id):
        return grant if grant is not None and ref == grant.data_rights_grant_id and grant.tenant_id == tenant_id else None

    resolver = EffectiveRightsResolver(grant_loader=loader, decision_repository=decisions)
    admission = ProviderRawRightsAdmission(
        resolver=resolver, grant_lookup=lookup,
        stream_lookup=lambda identity: [SimpleNamespace(stream_id=s) for s in streams],
    )
    return admission, decisions


TENANT_PARTNER = dict(
    connector_class="partner_feed", raw_data_owner="partner", source_relationship="partner_feed",
    contract_id="ctr_1", tenant_lake_allowed=True,
)
OLYMPUS = dict(
    connector_class="olympus_provider", raw_data_owner="olympus_labs",
    source_relationship="olympus_source", tenant_lake_allowed=False, olympus_baseline_allowed=True,
)


@pytest.mark.parametrize(
    "tenant,changes,expected_use",
    [
        ("tenant-1", {}, "tenant_lake"),
        ("tenant-1", TENANT_PARTNER, "tenant_lake"),
        (OLYMPUS_SOURCE_TENANT_ID, OLYMPUS, "olympus_baseline"),
        (OLYMPUS_SOURCE_TENANT_ID, dict(TENANT_PARTNER, tenant_lake_allowed=False, olympus_baseline_allowed=True), "olympus_baseline"),
    ],
)
@pytest.mark.asyncio
async def test_allowed_classes_admit_with_class_derived_use(tenant, changes, expected_use):
    record = _record(tenant=tenant)
    grant = _grant(record, **changes)
    admission, decisions = _admission(grant)
    evidence = await admission.admit(record)
    assert evidence.requested_use == expected_use == evidence.destination
    assert evidence.source_relationship == grant.source_relationship
    assert decisions.rows[evidence.rights_decision_ref]["allowed"] is True


@pytest.mark.parametrize(
    "tenant,changes",
    [
        ("tenant-1", {"tenant_lake_allowed": False}),                                  # tenant BYOD denied
        (OLYMPUS_SOURCE_TENANT_ID, dict(OLYMPUS, olympus_baseline_allowed=False)),     # Olympus denied
        ("tenant-1", dict(TENANT_PARTNER, tenant_lake_allowed=False)),                 # partner denied
        ("tenant-1", {"status": GrantStatus.REVOKED, "revoked_at": datetime.now(timezone.utc).isoformat()}),
        ("tenant-1", {"expires_at": "2020-01-01T00:00:00+00:00"}),
        ("tenant-1", {"connector_id": "shopify.admin.other_read"}),                   # wrong provider
        ("tenant-1", {"source_relationship": "personal_account", "connector_class": "olympus_provider"}),  # wrong relationship
        ("tenant-1", {"connector_class": "byok_gateway"}),
        ("tenant-1", {"connector_class": "tenant_import"}),
        ("tenant-1", {"source_relationship": "unclassified", "connector_class": "partner_feed", "contract_id": "c"}),
    ],
)
@pytest.mark.asyncio
async def test_denials_fail_closed(tenant, changes):
    record = _record(tenant=tenant)
    admission, _ = _admission(_grant(record, **changes))
    with pytest.raises(ProviderRawRightsDenied):
        await admission.admit(record)


@pytest.mark.asyncio
async def test_olympus_class_grant_under_customer_tenant_has_no_retention_use(monkeypatch):
    # Olympus-class evidence under a customer tenant must never reach that tenant's pipeline.
    reasons = []
    monkeypatch.setattr(
        rights_admission_module.metrics, "increment",
        lambda name, labels=None, **kw: reasons.append((labels or {}).get("reason")),
    )
    record = _record()
    grant = _grant(record, **dict(OLYMPUS, source_relationship="public_reference", raw_data_owner="public"))
    admission, _ = _admission(grant)
    with pytest.raises(ProviderRawRightsDenied):
        await admission.admit(record)
    assert reasons == ["no_raw_retention_use"]


@pytest.mark.asyncio
async def test_relationship_never_turns_a_denied_use_into_an_allow():
    record = _record()
    for relationship in ("organization_system", "personal_account", "unclassified"):
        admission, _ = _admission(_grant(record, source_relationship=relationship, tenant_lake_allowed=False))
        with pytest.raises(ProviderRawRightsDenied):
            await admission.admit(record)


@pytest.mark.asyncio
async def test_wrong_tenant_and_wrong_source_deny():
    record = _record()
    admission, _ = _admission(_grant(record, tenant_id="tenant-2"))
    with pytest.raises(ProviderRawRightsDenied):
        await admission.admit(record)
    admission, _ = _admission(_grant(record, source_id=provider_account_source_id("conn_1", "other")))
    with pytest.raises(ProviderRawRightsDenied):
        await admission.admit(record)


@pytest.mark.asyncio
async def test_non_durable_grant_store_denies_in_production(monkeypatch):
    record = _record()
    admission, _ = _admission(_grant(record))
    monkeypatch.setattr(settings, "env", Environment.PRODUCTION)
    with pytest.raises(ProviderRawRightsDenied):
        await admission.admit(record)


@pytest.mark.asyncio
async def test_stream_scope_admits_with_stream_grant_and_denies_without():
    record = _record(provider="polymarket.partner.activity_stream", account="", stream="activity")
    stream_source = provider_stream_source_id("conn_1", "activity")
    with_grant, _ = _admission(_grant(record, source_id=stream_source, **TENANT_PARTNER), streams=("activity",))
    assert (await with_grant.admit(record)).source_id == stream_source
    without_grant, _ = _admission(None, streams=("activity",))
    with pytest.raises(ProviderRawRightsDenied):
        await without_grant.admit(record)


@pytest.mark.asyncio
async def test_legacy_unclassified_tenant_byod_grant_still_admits():
    record = _record()
    legacy = _grant(record).model_dump()
    legacy.pop("source_relationship")
    grant = DataRightsGrant.model_validate(legacy)
    admission, _ = _admission(grant)
    evidence = await admission.admit(record)
    assert evidence.requested_use == "tenant_lake"
    assert evidence.source_relationship == "unclassified"


@pytest.mark.asyncio
async def test_partner_webhook_record_stays_partner_feed():
    record = _record(provider="polymarket.partner.activity_stream").model_copy(update={"acquisition_mode": "webhook"})
    admission, _ = _admission(_grant(record, **TENANT_PARTNER))
    assert (await admission.admit(record)).source_relationship == "partner_feed"


@pytest.mark.asyncio
async def test_pre_refactor_evidence_still_replays():
    record = _record()
    admission, _ = _admission(_grant(record))
    evidence = (await admission.admit(record)).model_dump(mode="json")
    evidence.pop("source_relationship")  # shape persisted before classification existed
    persisted = record.model_copy(update={"metadata": {PROVIDER_RAW_RIGHTS_METADATA_KEY: evidence}})
    await admission.authorize_replay(persisted)


@pytest.mark.asyncio
async def test_replay_denies_when_stored_use_differs_from_current_class_use():
    record = _record()
    admission, _ = _admission(_grant(record))
    evidence = (await admission.admit(record)).model_copy(
        update={"requested_use": "olympus_baseline", "destination": "olympus_baseline"},
    )
    persisted = record.model_copy(update={"metadata": {PROVIDER_RAW_RIGHTS_METADATA_KEY: evidence.model_dump(mode="json")}})
    with pytest.raises(ProviderRawRightsDenied):
        await admission.authorize_replay(persisted)


def test_retention_use_table():
    base = _grant(_record())
    assert raw_retention_use(base) == "tenant_lake"
    olympus = base.model_copy(update={"connector_class": "olympus_provider", "tenant_id": OLYMPUS_SOURCE_TENANT_ID})
    assert raw_retention_use(olympus) == "olympus_baseline"
    assert raw_retention_use(base.model_copy(update={"connector_class": "olympus_provider"})) is None
    assert raw_retention_use(base.model_copy(update={"connector_class": "partner_feed"})) == "tenant_lake"
    assert raw_retention_use(base.model_copy(update={"connector_class": "partner_feed", "tenant_id": OLYMPUS_SOURCE_TENANT_ID})) == "olympus_baseline"
    for cls in ("byok_gateway", "action_notifier", "dual_role", "tenant_import", ""):
        assert raw_retention_use(base.model_copy(update={"connector_class": cls})) is None
