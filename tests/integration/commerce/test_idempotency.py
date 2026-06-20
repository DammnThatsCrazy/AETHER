"""
Integration test: idempotency.
Submitting the same authorization_id twice returns the same result.
"""

from __future__ import annotations

import pytest

from tests.integration.commerce.conftest import AGENT_ID, PAYER_WALLET, RESOURCE_ID, TENANT


async def _run_to_auth(cp):
    req = await cp.issue_challenge(
        tenant_id=TENANT, resource_id=RESOURCE_ID,
        requester_id=AGENT_ID, requester_type="agent",
        chain="eip155:8453", asset_symbol="USDC",
    )
    approval, _ = await cp.request_approval(tenant_id=TENANT, challenge_id=req.challenge_id)
    await cp.apply_decision(
        tenant_id=TENANT, approval_id=approval.approval_id,
        action="approve", decided_by="op", reason="idem test",
    )
    auth = await cp.authorize_payment(
        tenant_id=TENANT, approval_id=approval.approval_id, payer=PAYER_WALLET,
    )
    return auth


@pytest.mark.asyncio
async def test_duplicate_submission_returns_same_entitlement(cp):
    auth = await _run_to_auth(cp)
    tx_hash = "0x" + "c" * 64

    result1 = await cp.verify_and_settle(
        tenant_id=TENANT, authorization_id=auth.authorization_id, tx_hash=tx_hash,
    )
    assert result1["verified"] is True

    # Second call with the same authorization_id
    result2 = await cp.verify_and_settle(
        tenant_id=TENANT, authorization_id=auth.authorization_id, tx_hash=tx_hash,
    )
    assert result2["verified"] is True
    assert result1["entitlement_id"] == result2["entitlement_id"]
    assert result1["receipt_id"] == result2["receipt_id"]


@pytest.mark.asyncio
async def test_different_tx_hash_same_auth_idempotent(cp):
    """tx_hash doesn't matter once result is cached — idempotency key is authorization_id."""
    auth = await _run_to_auth(cp)

    result1 = await cp.verify_and_settle(
        tenant_id=TENANT, authorization_id=auth.authorization_id, tx_hash="0x" + "d" * 64,
    )
    result2 = await cp.verify_and_settle(
        tenant_id=TENANT, authorization_id=auth.authorization_id, tx_hash="0x" + "e" * 64,
    )
    assert result1["entitlement_id"] == result2["entitlement_id"]
