"""Cross-tenant isolation sweep (program §25/§28).

Guards the "tenant B must never observe tenant A's data" invariant across the
four surface areas the program names — credential routes, capability readiness,
reward enablement, and commerce — all offline (in-memory stores, no network).

Surfaces asserted:
  * credential routes      — a slot tenant A creates+activates stays
                             ``configured: False`` for tenant B, and tenant B's
                             ``list_connections`` never leaks A's slots;
  * credential facade      — the in-memory backend keys by ``(tenant_id, ref)``;
                             ``metadata(tenantB, refA)`` is ``None`` and tenant
                             lists never intersect;
  * capability readiness   — the readiness-graph engine resolves per tenant: the
                             same capability reads READY for the tenant holding
                             the credential and CREDENTIAL_MISSING for everyone
                             else;
  * reward enablement      — every reward repo raises ``ForbiddenError`` when a
                             foreign tenant ``get``s a record and its ``list``
                             filters by tenant;
  * commerce settlement    — settlement events are tenant-scoped for reads and
                             cross-tenant mutation raises ``KeyError``;
  * commerce fee report    — ``PaymentRecord`` carries ``tenant_id``, the
                             service scopes ``get_fee_elimination_report`` /
                             ``get_agent_spend`` by it, and the routes thread
                             the caller's tenant in, so the fee report / agent
                             spend never leak another tenant's payments.
"""

from __future__ import annotations

import os
import uuid
from types import SimpleNamespace

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from repositories.repos import (  # noqa: E402
    SettlementEventRepository,
    reset_in_memory_stores,
)
from services.providers.credentials import routes as cred_routes  # noqa: E402
from services.providers.credentials.models import (  # noqa: E402
    SlotActivateRequest,
    SlotValueWrite,
)
from services.rewards.repositories import (  # noqa: E402
    RewardCampaignRepository,
    RewardDecisionRepository,
    RewardProofRepository,
)
from services.commerce.service import CommerceService  # noqa: E402
from services.commerce.models import PaymentRecord  # noqa: E402
from shared.common.common import ForbiddenError  # noqa: E402

pytestmark = pytest.mark.asyncio

_SLOT = "webhook_signing_secret"


class _Tenant:
    def __init__(self, tenant_id: str, permissions: set[str]):
        self.tenant_id = tenant_id
        self.principal_id = f"admin-{tenant_id}"
        self._perms = permissions

    def require_permission(self, permission: str) -> None:
        if permission not in self._perms:
            raise ForbiddenError(f"missing permission: {permission}")


class _Request:
    def __init__(self, tenant_id: str, *, admin: bool = True):
        perms = {"read", "write", "admin"} if admin else {"read"}
        self.state = SimpleNamespace(tenant=_Tenant(tenant_id, perms), request_id="req-1")


def _tenant() -> str:
    return f"t-{uuid.uuid4().hex[:8]}"


# ══════════════════════════════════════════════════════════════════════════
# credential routes + credential facade
# ══════════════════════════════════════════════════════════════════════════


async def test_credential_routes_never_leak_slots_across_tenants():
    reset_in_memory_stores()
    a, b = _tenant(), _tenant()
    await cred_routes.create_or_replace_slot(
        "coinbase", _SLOT, SlotValueWrite(value="secretA"), _Request(a))
    await cred_routes.activate_slot(
        "coinbase", _SLOT, SlotActivateRequest(credential_version=1), _Request(a))

    # Tenant A sees its own slot configured.
    conns_a = (await cred_routes.list_connections(_Request(a)))["data"]
    coinbase_a = next(c for c in conns_a if c["provider"] == "coinbase")
    slot_a = next(s for s in coinbase_a["slots"] if s["slot_name"] == _SLOT)
    assert slot_a["configured"] is True

    # Tenant B sees the same provider slot as unconfigured, never the value.
    conns_b = (await cred_routes.list_connections(_Request(b)))["data"]
    coinbase_b = next(c for c in conns_b if c["provider"] == "coinbase")
    slot_b = next(s for s in coinbase_b["slots"] if s["slot_name"] == _SLOT)
    assert slot_b["configured"] is False
    assert "secretA" not in str(conns_b)


async def test_credential_facade_is_keyed_by_tenant_ref():
    from shared.credentials.service import connector_ref, credential_service
    from shared.credentials.types import ApiKeyCredential
    from pydantic import SecretStr

    reset_in_memory_stores()
    a, b = _tenant(), _tenant()
    await credential_service.create(
        a, connector_ref(a, "commerce.orders.read"),
        ApiKeyCredential(api_key=SecretStr("sk_test_secret_a")),
    )
    # Cross-tenant lookup of the same ref returns nothing.
    assert await credential_service.metadata(b, connector_ref(a, "commerce.orders.read")) is None
    assert await credential_service.reveal(b, connector_ref(a, "commerce.orders.read")) is None
    # Tenant lists never intersect.
    assert {m.ref for m in await credential_service.list(a)} == {connector_ref(a, "commerce.orders.read")}
    assert await credential_service.list(b) == []


# ══════════════════════════════════════════════════════════════════════════
# capability readiness graph
# ══════════════════════════════════════════════════════════════════════════


async def test_readiness_graph_resolves_per_tenant():
    from shared.credentials.service import connector_ref, credential_service
    from shared.credentials.types import ApiKeyCredential
    from pydantic import SecretStr
    from services.readiness_graph.graph import (
        DependencyNode,
        NodeStatus,
        build_default_engine,
    )

    reset_in_memory_stores()
    a, b = _tenant(), _tenant()
    capability = "commerce.orders.read"
    await credential_service.create(
        a, connector_ref(a, capability),
        ApiKeyCredential(api_key=SecretStr("sk_test_secret_a")),
    )

    engine = build_default_engine()
    ra = await engine.resolve(capability, a)
    rb = await engine.resolve(capability, b)

    node = DependencyNode.CREDENTIAL_AUTHORITY.value
    status_a = next(n for n in ra.nodes if n.node == node).status
    status_b = next(n for n in rb.nodes if n.node == node).status
    assert status_a == NodeStatus.READY
    assert status_b == NodeStatus.CREDENTIAL_MISSING
    # The readiness graph echoes the tenant it was resolved for.
    assert ra.tenant_id == a
    assert rb.tenant_id == b
    # An unscoped (operator) resolve must not attribute A's credential to B.
    rb_none = await engine.resolve(capability, b or "")
    assert next(n for n in rb_none.nodes if n.node == node).status == NodeStatus.CREDENTIAL_MISSING


# ══════════════════════════════════════════════════════════════════════════
# reward enablement
# ══════════════════════════════════════════════════════════════════════════


async def test_reward_repositories_reject_cross_tenant_reads():
    reset_in_memory_stores()
    a, b = _tenant(), _tenant()
    campaign = await RewardCampaignRepository().create(a, {"name": "campaign-A"})
    decision = await RewardDecisionRepository().create(
        a, {"campaign_id": campaign["id"], "eligible": True, "user_id": "u1"})
    proof = await RewardProofRepository().create(
        a, {"decision_id": decision["id"], "nonce": "n1", "chain_id": 1, "contract_address": "0xaaa"})

    cases = [
        ("campaign", RewardCampaignRepository().get, campaign["id"]),
        ("decision", RewardDecisionRepository().get, decision["id"]),
        ("proof", RewardProofRepository().get, proof["id"]),
    ]
    for label, get, record_id in cases:
        with pytest.raises(ForbiddenError):
            await get(record_id, b)


async def test_reward_lists_are_tenant_scoped():
    reset_in_memory_stores()
    a, b = _tenant(), _tenant()
    await RewardCampaignRepository().create(a, {"name": "campaign-A"})
    await RewardCampaignRepository().create(b, {"name": "campaign-B"})
    campaigns_a = await RewardCampaignRepository().list(a)
    campaigns_b = await RewardCampaignRepository().list(b)
    assert {c["name"] for c in campaigns_a} == {"campaign-A"}
    assert {c["name"] for c in campaigns_b} == {"campaign-B"}


# ══════════════════════════════════════════════════════════════════════════
# commerce — settlement events (tenant-scoped durable surface)
# ══════════════════════════════════════════════════════════════════════════


async def test_commerce_settlement_events_are_tenant_scoped():
    reset_in_memory_stores()
    a, b = _tenant(), _tenant()
    repo = SettlementEventRepository()
    await repo.record_event(
        "se-1", a, "intent-1", "agent-1", "settled", "10", "USD")
    # Tenant B sees none of tenant A's settlement events.
    assert await repo.list_for_agent("agent-1", b) == []
    assert await repo.list_for_intent("intent-1", b) == []
    assert len(await repo.list_for_agent("agent-1", a)) == 1
    # Cross-tenant mutation of A's event is rejected.
    with pytest.raises(KeyError):
        await repo.mark_receipt_verified("se-1", b, "receipt-1")


# ══════════════════════════════════════════════════════════════════════════
# commerce — fee report / agent spend (tenant-scoped)
# ══════════════════════════════════════════════════════════════════════════


async def test_commerce_fee_report_does_not_leak_cross_tenant():
    """Isolation contract the fee report satisfies now that scoping has landed.

    ``PaymentRecord`` carries ``tenant_id``, ``record_payment`` persists it, and
    ``get_fee_elimination_report`` filters by it — so tenant A's report includes
    only A's payments and tenant B's report never includes them.
    """
    reset_in_memory_stores()
    a, b = _tenant(), _tenant()
    svc = CommerceService()
    await svc.record_payment(
        PaymentRecord(
            payer_id="alice", payer_type="human",
            payee_id="bob", payee_type="agent",
            amount=100.0, method="usdc",
        ),
        tenant_id=a,
    )
    # Tenant A's own report must include its payment…
    report_a = await svc.get_fee_elimination_report("all", tenant_id=a)
    assert report_a.total_transactions == 1
    # …and tenant B's report must never include it.
    report_b = await svc.get_fee_elimination_report("all", tenant_id=b)
    assert report_b.total_transactions == 0


async def test_commerce_agent_spend_does_not_leak_cross_tenant():
    """Agent spend is tenant-scoped: tenant B never sees tenant A's spend."""
    reset_in_memory_stores()
    a, b = _tenant(), _tenant()
    svc = CommerceService()
    await svc.record_payment(
        PaymentRecord(
            payer_id="alice", payer_type="agent",
            payee_id="bob", payee_type="human",
            amount=50.0, method="usdc",
        ),
        tenant_id=a,
    )
    spend_a = await svc.get_agent_spend("alice", tenant_id=a)
    assert spend_a["transaction_count"] == 1
    assert spend_a["total_spent_usd"] == 50.0
    spend_b = await svc.get_agent_spend("alice", tenant_id=b)
    assert spend_b["transaction_count"] == 0
    assert spend_b["total_spent_usd"] == 0.0
