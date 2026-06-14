"""
Integration test: rejection path.
Approval rejected → authorize_payment raises ControlPlaneError.
"""

from __future__ import annotations

import pytest

from tests.integration.commerce.conftest import AGENT_ID, PAYER_WALLET, RESOURCE_ID, TENANT


@pytest.mark.asyncio
async def test_rejection_blocks_authorize(cp):
    req = await cp.issue_challenge(
        tenant_id=TENANT, resource_id=RESOURCE_ID,
        requester_id=AGENT_ID, requester_type="agent",
        chain="eip155:8453", asset_symbol="USDC",
    )
    approval, _ = await cp.request_approval(tenant_id=TENANT, challenge_id=req.challenge_id)

    rejected = await cp.apply_decision(
        tenant_id=TENANT,
        approval_id=approval.approval_id,
        action="reject",
        decided_by="operator-001",
        reason="not authorized",
    )
    assert rejected.status.value == "rejected"

    from services.x402.control_plane import ControlPlaneError
    with pytest.raises(ControlPlaneError) as exc_info:
        await cp.authorize_payment(
            tenant_id=TENANT,
            approval_id=approval.approval_id,
            payer=PAYER_WALLET,
        )
    assert exc_info.value.code == "APPROVAL_NOT_APPROVED"


@pytest.mark.asyncio
async def test_pending_approval_blocks_authorize(cp):
    req = await cp.issue_challenge(
        tenant_id=TENANT, resource_id=RESOURCE_ID,
        requester_id=AGENT_ID, requester_type="agent",
        chain="eip155:8453", asset_symbol="USDC",
    )
    approval, _ = await cp.request_approval(tenant_id=TENANT, challenge_id=req.challenge_id)
    # Do NOT decide — approval stays PENDING

    from services.x402.control_plane import ControlPlaneError
    with pytest.raises(ControlPlaneError) as exc_info:
        await cp.authorize_payment(
            tenant_id=TENANT,
            approval_id=approval.approval_id,
            payer=PAYER_WALLET,
        )
    assert exc_info.value.code == "APPROVAL_NOT_APPROVED"
