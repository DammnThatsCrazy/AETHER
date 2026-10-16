"""Grant classification: relationship ↔ owner ↔ rights-class pairing (fail closed)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from connectors.integrations.connectors.base import ConnectorClass
from connectors.integrations.data_rights.models import DataRightsGrant, DataRightsGrantCreate
from connectors.integrations.data_rights.service import (
    DataRightsService,
    GrantClassificationError,
)
from shared.integration_contracts.source_relationship import OLYMPUS_SOURCE_TENANT_ID

ORG = dict(
    tenant_id="tenant_abc", source_id="provider-account:conn_1:shop-1",
    connector_id="shopify.admin.orders_read", connector_class="tenant_byod_data",
    data_category="commerce", raw_data_owner="tenant",
    source_relationship="organization_system", legal_basis="contract",
)
PERSONAL = dict(
    ORG, connector_id="coinbase.account.portfolio_read", data_category="financial",
    raw_data_owner="subject", source_relationship="personal_account",
    subject_ref="subject_1", consent_basis="consent:portfolio", legal_basis="consent",
)
PARTNER = dict(
    ORG, connector_id="polymarket.partner.activity_stream", connector_class="partner_feed",
    raw_data_owner="partner", source_relationship="partner_feed", contract_id="ctr_1",
)
OLYMPUS = dict(
    ORG, tenant_id=OLYMPUS_SOURCE_TENANT_ID, connector_id="dune.analytics.query_read",
    connector_class="olympus_provider", raw_data_owner="olympus_labs",
    source_relationship="olympus_source",
)


async def _create(**body):
    return await DataRightsService().create_grant(DataRightsGrantCreate(**body), "admin_1")


def test_partner_feed_is_a_connector_class():
    assert ConnectorClass.PARTNER_FEED.value == "partner_feed"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [ORG, PERSONAL, PARTNER, OLYMPUS])
async def test_valid_pairings_are_stored_with_their_relationship(body):
    grant = await _create(**body)
    assert grant.source_relationship == body["source_relationship"]
    assert grant.subject_ref == body.get("subject_ref")


@pytest.mark.asyncio
async def test_partner_feed_permissions_default_closed():
    grant = await _create(**PARTNER)
    assert not any([
        grant.tenant_lake_allowed, grant.tenant_graph_allowed, grant.tenant_insights_allowed,
        grant.olympus_baseline_allowed, grant.cross_tenant_aggregate_allowed,
        grant.model_training_allowed, grant.commercial_reuse_allowed,
    ])


def test_relationship_is_required_on_create():
    body = dict(ORG)
    body.pop("source_relationship")
    with pytest.raises(ValidationError):
        DataRightsGrantCreate(**body)


def test_raw_data_owner_is_curated_on_create():
    with pytest.raises(ValidationError):
        DataRightsGrantCreate(**dict(ORG, raw_data_owner="tenant_abc"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body,reason",
    [
        (dict(ORG, source_relationship="unclassified"), "unclassified_grant_creation_forbidden"),
        (dict(ORG, raw_data_owner="olympus_labs"), "raw_data_owner_mismatch"),
        (dict(ORG, connector_class="olympus_provider"), "rights_class_mismatch"),
        (dict(PERSONAL, subject_ref=None), "personal_account_requires_subject_consent"),
        (dict(PERSONAL, consent_basis=None), "personal_account_requires_subject_consent"),
        (dict(PERSONAL, legal_basis="operator_policy"), "personal_account_requires_subject_consent"),
        # The control that stops labelling an employee's personal account as organizational.
        (dict(ORG, subject_ref="employee_7"), "subject_ref_requires_personal_account"),
        (dict(PARTNER, contract_id=None), "partner_feed_requires_contract"),
        (dict(OLYMPUS, tenant_id="tenant_abc"), "olympus_scope_required"),
        (dict(ORG, tenant_id=OLYMPUS_SOURCE_TENANT_ID), "tenant_scope_required"),
    ],
)
async def test_invalid_pairings_are_rejected(body, reason):
    with pytest.raises(GrantClassificationError) as exc:
        await _create(**body)
    assert exc.value.reason == reason


def test_legacy_rows_without_relationship_read_as_unclassified():
    stored = dict(
        ORG, data_rights_grant_id="drg_legacy", data_sensitivity="unclassified",
        raw_data_owner="tenant_abc", granted_by_user_id="u", granted_at="2026-01-01T00:00:00+00:00",
        audit_event_id="audit_1",
    )
    stored.pop("source_relationship")
    assert DataRightsGrant.model_validate(stored).source_relationship == "unclassified"


@pytest.mark.asyncio
async def test_creation_audit_event_records_relationship():
    service = DataRightsService()
    await service.create_grant(DataRightsGrantCreate(**ORG), "admin_1")
    assert service._events[-1]["source_relationship"] == "organization_system"
