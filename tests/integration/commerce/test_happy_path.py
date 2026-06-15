"""
Integration test: full commerce lifecycle (happy path).
challenge → approve → authorize → verify → settle → entitle → grant
"""

from __future__ import annotations

import pytest

from tests.integration.commerce.conftest import (
    AGENT_ID, PAYER_WALLET, RESOURCE_ID, TENANT,
)


@pytest.mark.asyncio
async def test_full_lifecycle_happy_path(cp):
    # Step 1: Issue challenge
    req = await cp.issue_challenge(
        tenant_id=TENANT,
        resource_id=RESOURCE_ID,
        requester_id=AGENT_ID,
        requester_type="agent",
        chain="eip155:8453",
        asset_symbol="USDC",
    )
    assert req.challenge_id.startswith("chg_")
    assert req.tenant_id == TENANT
    assert req.amount_usd == 1.0

    # Step 2: Request approval
    approval, _decision = await cp.request_approval(tenant_id=TENANT, challenge_id=req.challenge_id)
    assert approval.status.value == "pending"
    assert approval.challenge_id == req.challenge_id

    # Step 3: Approve
    approved = await cp.apply_decision(
        tenant_id=TENANT,
        approval_id=approval.approval_id,
        action="approve",
        decided_by="operator-001",
        reason="happy path test",
    )
    assert approved.status.value == "approved"

    # Step 4: Authorize payment
    auth = await cp.authorize_payment(
        tenant_id=TENANT,
        approval_id=approved.approval_id,
        payer=PAYER_WALLET,
    )
    assert auth.authorization_id.startswith("auth_")
    assert auth.amount_usd == 1.0
    assert auth.chain == "eip155:8453"

    # Step 5: Verify + settle (local mode: always succeeds)
    tx_hash = "0x" + "a" * 64
    result = await cp.verify_and_settle(
        tenant_id=TENANT,
        authorization_id=auth.authorization_id,
        tx_hash=tx_hash,
    )
    assert result["verified"] is True
    assert result["settlement_state"] == "settled"
    assert "entitlement_id" in result
    assert "settlement_id" in result
    assert result["entitlement_id"].startswith("ent_")

    # Step 6: Grant access
    grant = await cp.grant_access(
        tenant_id=TENANT,
        entitlement_id=result["entitlement_id"],
        request_url="/v1/integration/test",
        request_method="GET",
    )
    assert grant["status"] == "granted"
    assert grant["grant_id"].startswith("grt_")


@pytest.mark.asyncio
async def test_explain_traces_full_lifecycle(cp):
    """explain() must return a complete lifecycle trace after the happy path."""
    req = await cp.issue_challenge(
        tenant_id=TENANT, resource_id=RESOURCE_ID,
        requester_id=AGENT_ID, requester_type="agent",
        chain="eip155:8453", asset_symbol="USDC",
    )
    approval, _ = await cp.request_approval(tenant_id=TENANT, challenge_id=req.challenge_id)
    await cp.apply_decision(
        tenant_id=TENANT, approval_id=approval.approval_id,
        action="approve", decided_by="op", reason="trace test",
    )
    auth = await cp.authorize_payment(
        tenant_id=TENANT, approval_id=approval.approval_id, payer=PAYER_WALLET,
    )
    await cp.verify_and_settle(
        tenant_id=TENANT, authorization_id=auth.authorization_id, tx_hash="0x" + "b" * 64,
    )

    trace = await cp.explain(TENANT, req.challenge_id)
    assert trace.requirement is not None
    assert trace.approval is not None
    assert trace.approval.challenge_id == req.challenge_id
    assert trace.settlement is not None
    assert trace.entitlement is not None
