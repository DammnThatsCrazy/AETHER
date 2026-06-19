"""Unit tests: data rights ledger — fail-closed policy checks."""
from __future__ import annotations

import pytest

from services.integrations.data_rights.models import DataRightsGrantCreate, GrantStatus
from services.integrations.data_rights.service import (
    DataRightsService,
    can_use_for_commercial_reuse,
    can_use_for_cross_tenant_aggregate,
    can_use_for_model_training,
    can_write_olympus_baseline,
    can_write_tenant_lake,
)


def _make_service() -> DataRightsService:
    return DataRightsService()


def _make_grant_body(**overrides) -> DataRightsGrantCreate:
    defaults = {
        "tenant_id": "tenant_abc",
        "source_id": "src_001",
        "connector_id": "dune_api",
        "connector_class": "olympus_provider",
        "data_category": "onchain",
        "data_sensitivity": "unclassified",
        "raw_data_owner": "olympus_labs",
    }
    defaults.update(overrides)
    return DataRightsGrantCreate(**defaults)


@pytest.mark.asyncio
async def test_grant_creation_basic():
    svc = _make_service()
    grant = await svc.create_grant(_make_grant_body(), granted_by_user_id="user_1")
    assert grant.data_rights_grant_id.startswith("drg_")
    assert grant.status == GrantStatus.ACTIVE
    assert grant.tenant_id == "tenant_abc"


@pytest.mark.asyncio
async def test_olympus_provider_baseline_auto_set():
    """Olympus provider sources automatically get olympus_baseline_allowed=True."""
    svc = _make_service()
    body = _make_grant_body(connector_class="olympus_provider", olympus_baseline_allowed=False)
    grant = await svc.create_grant(body, granted_by_user_id="user_1")
    # olympus_baseline_allowed override: olympus_provider = True regardless of input
    assert grant.olympus_baseline_allowed is True


@pytest.mark.asyncio
async def test_model_training_default_false():
    """model_training_allowed must default to False even for Olympus providers."""
    svc = _make_service()
    grant = await svc.create_grant(_make_grant_body(), granted_by_user_id="user_1")
    assert grant.model_training_allowed is False


@pytest.mark.asyncio
async def test_cross_tenant_aggregate_default_false():
    svc = _make_service()
    grant = await svc.create_grant(_make_grant_body(), granted_by_user_id="user_1")
    assert grant.cross_tenant_aggregate_allowed is False


@pytest.mark.asyncio
async def test_commercial_reuse_default_false():
    svc = _make_service()
    grant = await svc.create_grant(_make_grant_body(), granted_by_user_id="user_1")
    assert grant.commercial_reuse_allowed is False


@pytest.mark.asyncio
async def test_tenant_byod_connector_class_baseline_not_set():
    """Tenant BYOD data does NOT get olympus_baseline_allowed=True."""
    svc = _make_service()
    body = _make_grant_body(connector_class="tenant_byod_data", olympus_baseline_allowed=False)
    grant = await svc.create_grant(body, granted_by_user_id="user_1")
    assert grant.olympus_baseline_allowed is False


@pytest.mark.asyncio
async def test_revoke_blocks_all_use():
    """Revoked grants must deny all policy checks."""
    from services.integrations.data_rights.models import DataRightsGrantRevoke
    svc = _make_service()
    body = _make_grant_body(
        connector_class="olympus_provider",
        olympus_baseline_allowed=True,
        model_training_allowed=True,
    )
    grant = await svc.create_grant(body, granted_by_user_id="user_1")
    assert can_write_olympus_baseline(grant) is True

    revoke_body = DataRightsGrantRevoke(
        revocation_reason="compliance_violation",
        revoked_by_user_id="operator_1",
    )
    revoked = await svc.revoke_grant(grant.data_rights_grant_id, revoke_body)
    assert revoked.status == GrantStatus.REVOKED
    assert can_write_olympus_baseline(revoked) is False
    assert can_use_for_model_training(revoked) is False
    assert can_use_for_cross_tenant_aggregate(revoked) is False


@pytest.mark.asyncio
async def test_policy_check_olympus_baseline():
    svc = _make_service()
    grant = await svc.create_grant(
        _make_grant_body(connector_class="olympus_provider"),
        granted_by_user_id="user_1",
    )
    result = await svc.check_policy(grant.data_rights_grant_id, "olympus_baseline")
    assert result.allowed is True
    assert result.reason == "allowed"


@pytest.mark.asyncio
async def test_policy_check_model_training_denied():
    svc = _make_service()
    grant = await svc.create_grant(
        _make_grant_body(connector_class="olympus_provider", model_training_allowed=False),
        granted_by_user_id="user_1",
    )
    result = await svc.check_policy(grant.data_rights_grant_id, "model_training")
    assert result.allowed is False


@pytest.mark.asyncio
async def test_policy_check_unknown_grant_denied():
    svc = _make_service()
    result = await svc.check_policy("nonexistent_grant_id", "olympus_baseline")
    assert result.allowed is False
    assert result.reason == "grant_not_found"


@pytest.mark.asyncio
async def test_list_grants_filtered_by_tenant():
    svc = _make_service()
    g1 = await svc.create_grant(_make_grant_body(tenant_id="tenant_A"), granted_by_user_id="u")
    g2 = await svc.create_grant(_make_grant_body(tenant_id="tenant_B"), granted_by_user_id="u")

    a_grants = await svc.list_grants(tenant_id="tenant_A")
    b_grants = await svc.list_grants(tenant_id="tenant_B")

    assert len(a_grants) == 1
    assert len(b_grants) == 1
    assert a_grants[0].tenant_id == "tenant_A"
    assert b_grants[0].tenant_id == "tenant_B"
