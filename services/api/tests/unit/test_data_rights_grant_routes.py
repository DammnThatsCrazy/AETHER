"""Tenant self-service may grant only its own personal/organization sources."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import governance.security.request_context as request_context
from connectors.integrations.data_rights import routes
from connectors.integrations.data_rights.models import DataRightsGrantCreate
from connectors.integrations.data_rights.service import DataRightsService
from shared.common.common import BadRequestError, ForbiddenError
from shared.integration_contracts.source_relationship import OLYMPUS_SOURCE_TENANT_ID

ORG = dict(
    tenant_id="tenant_abc", source_id="provider-account:conn_1:shop-1",
    connector_id="shopify.admin.orders_read", connector_class="tenant_byod_data",
    data_category="commerce", raw_data_owner="tenant", source_relationship="organization_system",
)
OLYMPUS = dict(
    ORG, tenant_id=OLYMPUS_SOURCE_TENANT_ID, connector_id="dune.analytics.query_read",
    connector_class="olympus_provider", raw_data_owner="olympus_labs",
    source_relationship="olympus_source",
)


def _request(tenant_id="tenant_abc"):
    tenant = SimpleNamespace(tenant_id=tenant_id, user_id="admin_1", require_permission=lambda p: None)
    return SimpleNamespace(state=SimpleNamespace(tenant=tenant))


@pytest.fixture(autouse=True)
def isolated_service(monkeypatch):
    monkeypatch.setattr(routes, "data_rights_service", DataRightsService())


@pytest.mark.asyncio
async def test_tenant_admin_creates_organization_grant():
    response = await routes.create_grant(DataRightsGrantCreate(**ORG), _request())
    assert response["data"]["source_relationship"] == "organization_system"


@pytest.mark.asyncio
@pytest.mark.parametrize("relationship", ["olympus_source", "partner_feed", "public_reference", "internal_system"])
async def test_tenant_cannot_claim_operator_relationships(relationship):
    body = DataRightsGrantCreate(**dict(ORG, source_relationship=relationship))
    with pytest.raises(ForbiddenError):
        await routes.create_grant(body, _request())


@pytest.mark.asyncio
async def test_tenant_cannot_claim_the_olympus_scope():
    body = DataRightsGrantCreate(**dict(ORG, tenant_id=OLYMPUS_SOURCE_TENANT_ID))
    with pytest.raises((ForbiddenError, BadRequestError)):
        await routes.create_grant(body, _request(tenant_id=OLYMPUS_SOURCE_TENANT_ID))


@pytest.mark.asyncio
async def test_tenant_classification_failure_is_a_bad_request():
    body = DataRightsGrantCreate(**dict(ORG, subject_ref="employee_7"))
    with pytest.raises(BadRequestError):
        await routes.create_grant(body, _request())


@pytest.mark.asyncio
async def test_operator_creates_olympus_grant(monkeypatch):
    monkeypatch.setattr(request_context, "require_kyber_operator", lambda request: SimpleNamespace(actor_id="op_1"))
    response = await routes.admin_create_grant(DataRightsGrantCreate(**OLYMPUS), _request())
    assert response["data"]["granted_by_user_id"] == "op_1"
    assert response["data"]["source_relationship"] == "olympus_source"


@pytest.mark.asyncio
async def test_operator_cannot_mint_tenant_relationships(monkeypatch):
    monkeypatch.setattr(request_context, "require_kyber_operator", lambda request: SimpleNamespace(actor_id="op_1"))
    with pytest.raises(ForbiddenError):
        await routes.admin_create_grant(DataRightsGrantCreate(**ORG), _request())


@pytest.mark.asyncio
async def test_non_operator_is_refused(monkeypatch):
    def deny(request):
        raise ForbiddenError("Kyber operator access required")

    monkeypatch.setattr(request_context, "require_kyber_operator", deny)
    with pytest.raises(ForbiddenError):
        await routes.admin_create_grant(DataRightsGrantCreate(**OLYMPUS), _request())
