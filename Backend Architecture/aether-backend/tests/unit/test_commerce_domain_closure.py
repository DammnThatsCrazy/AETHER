"""
Unit tests for the commerce-domain closure pieces:

    - rail matrix (every configured rail reports one of four support buckets,
      never silent — unknown rails raise UnknownRailError)
    - commerce lifecycle reconciliation (rebuild_from_silver /
      verify_graph_consistency / reconciliation_drift / reconcile_commerce)
    - commerce metering (challenged / paid / entitled / access_granted records)
    - tenant signer authority (observation-only register / list / check /
      deactivate)
    - control-plane metering integration (a full lifecycle writes meter records)

All tests run against the in-memory backends (AETHER_ENV=local); per-test store
singletons are reset before each test.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

os.environ.setdefault("AETHER_ENV", "local")

from repositories.repos import reset_in_memory_stores
from services.commerce.metering import (
    get_metering_service,
    reset_metering_service,
)
from services.commerce.rail_matrix import (
    RailSupport,
    UnknownRailError,
    all_declared_rails,
    classify_rail,
    is_supported_for_production,
    is_supported_for_sandbox,
    native_rails,
    unsupported_reason,
)
from services.commerce.reconciliation import (
    SILVER_STATUS_AVAILABLE,
    SILVER_STATUS_UNAVAILABLE,
    CommerceReconciler,
    CommerceSilverFactsReader,
    get_commerce_reconciler,
    reset_commerce_reconciler,
)
from services.x402.control_plane import reset_control_plane
from services.x402.facilitators import (
    reset_asset_registry,
    reset_facilitator_registry,
)
from services.x402.signer_authority import (
    SignerAuthority,
    reset_signer_authority,
)


def _run(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


@pytest.fixture(autouse=True)
def _reset():
    from services.silver.writer import reset_local_tables
    from services.x402 import (
        approvals as apv,
        commerce_store as cs,
        entitlements as ent,
        idempotency as idem,
        policies as pol,
        resources as res,
        settlement as stl,
        verification as ver,
    )

    # Reset the commerce store AND every store-capturing x402 singleton so each
    # test rebuilds a fresh, internally-consistent store graph. This mirrors the
    # commerce suite's fixture (tests/commerce/test_lifecycle.py) exactly: the
    # in-memory commerce store is replaced (reset_commerce_store) and each
    # module-level singleton is dropped so it re-binds to the new store on next
    # construction. Clearing the CURRENT store's collections in place is NOT
    # enough under pytest-xdist: when another x402 test file runs earlier in the
    # same worker, its singletons were constructed against a store object that a
    # later reset_commerce_store() REPLACED, so they permanently reference a
    # stale store — a later test's seeds (written through the current store) are
    # then invisible to the stale resource registry / verification engine /
    # approval service / settlement tracker / entitlement service / policy
    # engine, the signer gate reads empty signer state, and verification reverts
    # on-chain. Nulling every store-capturing singleton removes the staleness
    # regardless of what ran before in the worker.
    cs.reset_commerce_store()
    idem.reset_idempotency_store()
    reset_control_plane()
    res._registry = None
    apv._service = None
    ver._engine = None
    stl._tracker = None
    ent._service = None
    pol._engine = None
    reset_signer_authority()
    reset_facilitator_registry()
    reset_asset_registry()
    reset_commerce_reconciler()
    reset_metering_service()
    reset_local_tables()
    yield
    reset_in_memory_stores()
    cs.reset_commerce_store()
    idem.reset_idempotency_store()
    reset_control_plane()
    res._registry = None
    apv._service = None
    ver._engine = None
    stl._tracker = None
    ent._service = None
    pol._engine = None
    reset_signer_authority()
    reset_facilitator_registry()
    reset_asset_registry()
    reset_commerce_reconciler()
    reset_metering_service()
    reset_local_tables()


# ═══════════════════════════════════════════════════════════════════════════
# RAIL MATRIX
# ═══════════════════════════════════════════════════════════════════════════


def test_rail_matrix_production_bucket():
    assert classify_rail("onchain_claim") is RailSupport.SUPPORTED_PRODUCTION
    assert classify_rail("tenant_webhook") is RailSupport.SUPPORTED_PRODUCTION
    assert classify_rail("recommend_only") is RailSupport.SUPPORTED_PRODUCTION
    assert classify_rail("eip155:8453") is RailSupport.SUPPORTED_PRODUCTION
    assert classify_rail("solana:mainnet") is RailSupport.SUPPORTED_PRODUCTION


def test_rail_matrix_sandbox_bucket():
    assert classify_rail("onchain_claim.svm") is RailSupport.SUPPORTED_SANDBOX
    assert classify_rail("eip155:84532") is RailSupport.SUPPORTED_SANDBOX
    assert classify_rail("solana:devnet") is RailSupport.SUPPORTED_SANDBOX


def test_rail_matrix_beta_bucket():
    assert classify_rail("stripe_credit") is RailSupport.SUPPORTED_BETA
    assert classify_rail("loyalty_points") is RailSupport.SUPPORTED_BETA
    assert classify_rail("coupon") is RailSupport.SUPPORTED_BETA
    assert classify_rail("internal_credit") is RailSupport.SUPPORTED_BETA
    assert classify_rail("x402_credit") is RailSupport.SUPPORTED_BETA


def test_rail_matrix_intentionally_unsupported_has_reason():
    assert classify_rail("ach") is RailSupport.INTENTIONALLY_UNSUPPORTED
    assert classify_rail("wire") is RailSupport.INTENTIONALLY_UNSUPPORTED
    assert classify_rail("card_surcharge") is RailSupport.INTENTIONALLY_UNSUPPORTED
    assert classify_rail("crypto_custody") is RailSupport.INTENTIONALLY_UNSUPPORTED
    assert unsupported_reason("ach")
    assert unsupported_reason("wire")


def test_rail_matrix_aliases_resolve():
    # Aliases never invent support — they point at declared native rails.
    assert classify_rail("base_usdc") is RailSupport.SUPPORTED_PRODUCTION
    assert classify_rail("solana_usdc") is RailSupport.SUPPORTED_PRODUCTION
    assert classify_rail("on_chain_claim") is RailSupport.SUPPORTED_PRODUCTION


def test_rail_matrix_unknown_rail_raises():
    with pytest.raises(UnknownRailError):
        classify_rail("made_up_rail_xyz")
    with pytest.raises(UnknownRailError):
        is_supported_for_production("made_up_rail_xyz")


def test_rail_matrix_support_helpers():
    assert is_supported_for_production("onchain_claim") is True
    assert is_supported_for_production("onchain_claim.svm") is False
    assert is_supported_for_sandbox("onchain_claim.svm") is True
    assert is_supported_for_sandbox("stripe_credit") is False


def test_rail_matrix_all_declared_nonempty_and_complete():
    declared = all_declared_rails()
    assert len(declared) >= 20
    # Every declared rail must resolve to one of the four buckets (never silent).
    for rail in declared:
        assert classify_rail(rail) in (
            RailSupport.SUPPORTED_PRODUCTION,
            RailSupport.SUPPORTED_SANDBOX,
            RailSupport.SUPPORTED_BETA,
            RailSupport.INTENTIONALLY_UNSUPPORTED,
        )
    assert "onchain_claim" in native_rails()


# ═══════════════════════════════════════════════════════════════════════════
# COMMERCE METERING
# ═══════════════════════════════════════════════════════════════════════════


def test_metering_records_and_summarizes():
    svc = get_metering_service()
    _run(svc.record_challenge(
        "tenant_m", resource_id="res_a", holder_id="agent_1",
        amount_usd=5.0, chain="eip155:8453", asset_symbol="USDC",
    ))
    _run(svc.record_payment(
        "tenant_m", resource_id="res_a", holder_id="agent_1",
        amount_usd=5.0, chain="eip155:8453", asset_symbol="USDC",
        authorization_id="auth_1",
    ))
    _run(svc.record_access_granted(
        "tenant_m", resource_id="res_a", holder_id="agent_1",
        entitlement_id="ent_1",
    ))
    summary = _run(svc.summarize("tenant_m"))
    assert summary["tenant_id"] == "tenant_m"
    assert summary["total_records"] == 3
    assert summary["by_type"]["challenge_issued"]["count"] == 1
    assert summary["by_type"]["payment_paid"]["count"] == 1
    assert summary["by_type"]["payment_paid"]["amount_usd"] == 5.0
    assert summary["by_type"]["access_granted"]["count"] == 1


def test_metering_rejects_unknown_type():
    svc = get_metering_service()
    with pytest.raises(ValueError):
        _run(svc.record("tenant_m", "made_up_meter"))


# ═══════════════════════════════════════════════════════════════════════════
# COMMERCE RECONCILIATION
# ═══════════════════════════════════════════════════════════════════════════


def _write_silver_fact(tenant_id: str, **fields) -> None:
    from services.silver.writer import _local_tables
    table = _local_tables.setdefault("silver_x402_flow_facts", {})
    row = {
        "tenant_id": tenant_id,
        "occurred_at": fields.get("occurred_at", "2026-08-08T00:00:00+00:00"),
        "flow_type": fields.get("flow_type", "x402_payment_verified_observed"),
        "settled": fields.get("settled", True),
        "settlement_tx_hash": fields.get("settlement_tx_hash", ""),
        "source_event_id": fields.get("source_event_id", f"evt_{uuid.uuid4().hex[:8]}"),
        "resource_id": fields.get("resource_id", "res_recon"),
        "amount": fields.get("amount", 5.0),
        "currency": "USD",
        "payload": fields.get("payload", {}),
    }
    table[row["source_event_id"]] = row


def test_reconciliation_rebuild_from_silver():
    _write_silver_fact("tenant_recon", settlement_tx_hash="0xabc123", source_event_id="evt_1")
    _write_silver_fact("tenant_recon", flow_type="x402_challenge_observed", settled=False,
                       source_event_id="evt_2")
    reconciler = CommerceReconciler()
    rebuilt = _run(reconciler.rebuild_from_silver("tenant_recon"))
    assert rebuilt["tenant_id"] == "tenant_recon"
    assert rebuilt["count"] == 2
    assert rebuilt["paid_count"] == 1
    paid = next(f for f in rebuilt["facts"] if f["flow_type"].startswith("x402_payment"))
    assert paid["settled"] is True
    assert paid["settlement_tx_hash"] == "0xabc123"


def test_reconciliation_verify_graph_consistency():
    reconciler = CommerceReconciler()
    # A settlement referencing a non-existent receipt must be flagged.
    store = reconciler._store
    from services.x402.commerce_models import (
        Entitlement,
        EntitlementStatus,
        Settlement,
        SettlementState,
    )
    orphan = Settlement(
        tenant_id="tenant_recon",
        challenge_id="chg_x",
        receipt_id="rcpt_missing",
        tx_hash="0xdef",
        chain="eip155:8453",
        amount_usd=1.0,
        facilitator_id="fac_local_aether",
        state=SettlementState.PENDING,
    )
    _run(store.put_settlement(orphan))
    expired = Entitlement(
        tenant_id="tenant_recon",
        holder_id="agent_1",
        holder_type="agent",
        resource_id="res_x",
        scope="read",
        status=EntitlementStatus.ACTIVE,
        settlement_id=orphan.settlement_id,
        expires_at="2000-01-01T00:00:00+00:00",
    )
    _run(store.put_entitlement(expired))

    report = _run(reconciler.verify_graph_consistency("tenant_recon"))
    assert report["verified"] is False
    kinds = {i["kind"] for i in report["issues"]}
    assert "missing_receipt" in kinds
    assert "stale_entitlement" in kinds


def test_reconciliation_drift_flags_silver_paid_not_settled():
    reconciler = CommerceReconciler()
    _write_silver_fact("tenant_recon", settlement_tx_hash="0xpaid_on_chain",
                       source_event_id="evt_paid")
    drift = _run(reconciler.reconciliation_drift("tenant_recon"))
    kinds = {d["kind"] for d in drift}
    assert "silver_paid_not_settled" in kinds


def test_reconciliation_reconcile_commerce_full_run():
    reconciler = CommerceReconciler()
    _write_silver_fact("tenant_recon", settlement_tx_hash="0x1", source_event_id="evt_a")
    report = _run(reconciler.reconcile_commerce("tenant_recon"))
    assert report["tenant_id"] == "tenant_recon"
    assert report["rebuilt_from_silver"]["count"] == 1
    assert "graph_consistency" in report
    assert "drift" in report
    assert report["reconciled_at"]


def test_reconciliation_singleton_cycle():
    get_commerce_reconciler()
    reset_commerce_reconciler()
    assert get_commerce_reconciler() is not None


def test_reconciliation_silver_reader_empty_local_read_is_empty_list():
    # Genuine empty read (in-memory backend, no rows) must still be [] — not None.
    reader = CommerceSilverFactsReader()
    assert _run(reader.read("tenant_recon")) == []


def test_reconciliation_silver_reader_unavailable_on_query_failure(monkeypatch):
    # PostgreSQL is reachable but the Silver query fails: the read must NOT be
    # fabricated into an empty fact set that looks authoritative.
    class _ExplodingPool:
        async def fetch(self, query, *params):
            raise RuntimeError("silver_x402_flow_facts query failed")

    async def _broken_pool():
        return _ExplodingPool()

    monkeypatch.setattr(
        "services.commerce.reconciliation.get_pool", _broken_pool
    )
    reader = CommerceSilverFactsReader()
    assert _run(reader.read("tenant_recon")) is None


def test_reconciliation_rebuild_reports_unavailable_when_silver_read_fails(monkeypatch):
    class _ExplodingPool:
        async def fetch(self, query, *params):
            raise RuntimeError("silver_x402_flow_facts query failed")

    async def _broken_pool():
        return _ExplodingPool()

    monkeypatch.setattr(
        "services.commerce.reconciliation.get_pool", _broken_pool
    )
    reconciler = CommerceReconciler()
    rebuilt = _run(reconciler.rebuild_from_silver("tenant_recon"))
    assert rebuilt["status"] == SILVER_STATUS_UNAVAILABLE
    assert rebuilt["count"] == 0
    assert rebuilt["facts"] == []
    # The snapshot is explicitly non-authoritative, not a zero-count success.
    assert "not authoritative" in rebuilt["detail"]


def test_reconciliation_drift_surfaces_silver_unavailable_not_false_drift(monkeypatch):
    class _ExplodingPool:
        async def fetch(self, query, *params):
            raise RuntimeError("silver_x402_flow_facts query failed")

    async def _broken_pool():
        return _ExplodingPool()

    monkeypatch.setattr(
        "services.commerce.reconciliation.get_pool", _broken_pool
    )
    reconciler = CommerceReconciler()
    # A verified receipt exists in the store; with a working Silver read this
    # would be reported as paid_but_no_silver_fact. With Silver down it must
    # surface as an outage instead.
    store = reconciler._store
    from services.x402.commerce_models import PaymentReceipt
    _run(store.put_receipt(PaymentReceipt(
        tenant_id="tenant_recon",
        receipt_id="rcpt_ok",
        authorization_id="auth_1",
        challenge_id="chg_1",
        tx_hash="0xpaid",
        chain="eip155:8453",
        asset_symbol="USDC",
        amount_usd=5.0,
        payer="0xpayer",
        recipient="0xrecipient",
        verified=True,
    )))
    drift = _run(reconciler.reconciliation_drift("tenant_recon"))
    kinds = {d["kind"] for d in drift}
    assert "silver_unavailable" in kinds
    assert "paid_but_no_silver_fact" not in kinds
    assert "silver_paid_not_settled" not in kinds


def test_reconciliation_rebuild_available_status_on_success():
    _write_silver_fact("tenant_recon", settlement_tx_hash="0xabc", source_event_id="evt_status")
    reconciler = CommerceReconciler()
    rebuilt = _run(reconciler.rebuild_from_silver("tenant_recon"))
    assert rebuilt["status"] == SILVER_STATUS_AVAILABLE
    assert rebuilt["count"] == 1


# ═══════════════════════════════════════════════════════════════════════════
# TENANT SIGNER AUTHORITY (observation-only)
# ═══════════════════════════════════════════════════════════════════════════


def test_signer_authority_register_and_check():
    authority = SignerAuthority()
    ref = _run(authority.register_signer(
        "tenant_s", "0xAaBbCcDdEeFf00112233445566778899aAbBcCdD",
    ))
    assert ref.tenant_id == "tenant_s"
    assert _run(authority.is_authorized_signer(
        "tenant_s", "0xAAbbccddeeff00112233445566778899aabbccdd"
    )) is True  # case-insensitive
    assert _run(authority.count_active("tenant_s")) == 1


def test_signer_authority_fail_closed():
    authority = SignerAuthority()
    # No signer registered → any address resolves False (fail-closed).
    assert _run(authority.is_authorized_signer("tenant_s", "0xabc")) is False
    # Tenant-scoped: another tenant's signer is never authorized here.
    _run(authority.register_signer("tenant_s", "0xaaa"))
    assert _run(authority.is_authorized_signer("tenant_other", "0xaaa")) is False


def test_signer_authority_role_filter_and_deactivate():
    authority = SignerAuthority()
    _run(authority.register_signer("tenant_s", "0xpay", role="payment"))
    _run(authority.register_signer("tenant_s", "0xobs", role="observer"))
    assert _run(authority.is_authorized_signer("tenant_s", "0xpay", role="payment")) is True
    assert _run(authority.is_authorized_signer("tenant_s", "0xpay", role="observer")) is False

    refs = _run(authority.list_signers("tenant_s"))
    assert len(refs) == 2
    _run(authority.deactivate_signer("tenant_s", refs[0].signer_ref_id))
    assert _run(authority.is_authorized_signer("tenant_s", refs[0].address)) is False
    assert _run(authority.count_active("tenant_s")) == 1


def test_signer_authority_payer_gate_fail_closed_when_all_signers_revoked():
    authority = SignerAuthority()

    # (a) A tenant with NO signer registry is unaffected: the gate allows.
    assert _run(authority.is_payer_authorized("tenant_empty", "0xaaa")) == (True, None)

    # (b) A tenant WITH an active signer: only that signer passes.
    _run(authority.register_signer("tenant_gated", "0xa11ce"))
    assert _run(authority.is_payer_authorized("tenant_gated", "0xa11ce")) == (True, None)
    ok, reason = _run(authority.is_payer_authorized("tenant_gated", "0xstranger"))
    assert ok is False
    assert "not an active tenant-authorized signer" in reason

    # (c) Deactivating the tenant's ONLY signer keeps the gate fail-closed:
    #     every payer — including the former signer — is now rejected, instead
    #     of the count_active()==0 branch reopening the gate for every payer.
    refs = _run(authority.list_signers("tenant_gated"))
    assert len(refs) == 1
    _run(authority.deactivate_signer("tenant_gated", refs[0].signer_ref_id))
    assert _run(authority.count_active("tenant_gated")) == 0
    for payer in ("0xa11ce", "0xstranger"):
        ok, reason = _run(authority.is_payer_authorized("tenant_gated", payer))
        assert ok is False
        assert "no active signer references" in reason


# ═══════════════════════════════════════════════════════════════════════════
# SIGNER AUTHORITY ENFORCEMENT AT THE PROOF-VERIFICATION BOUNDARY
# ═══════════════════════════════════════════════════════════════════════════

async def _authorize_for(plane, tenant, resources, payer: str):
    """Drive the lifecycle up to an authorized payment for `payer`."""
    r = resources[0]
    challenge = await plane.issue_challenge(
        tenant_id=tenant, resource_id=r.resource_id, requester_id="agent_s"
    )
    approval, _ = await plane.request_approval(tenant, challenge.challenge_id)
    await plane.apply_decision(tenant, approval.approval_id, "approve", "ops", "ok")
    return await plane.authorize_payment(tenant, approval.approval_id, payer)


@pytest.mark.asyncio
async def test_verify_and_settle_rejects_unregistered_payer_when_signers_configured():
    """A tenant that HAS registered signer references fails closed at the
    proof-verification boundary: a payment proof from an unregistered payer is
    rejected even though chain/facilitator verification would succeed."""
    from services.x402.control_plane import get_control_plane
    from services.x402.facilitators import seed_facilitators_and_assets
    from services.x402.resources import seed_aether_native_resources

    tenant = "t_signer_enforce"
    resources = await seed_aether_native_resources(tenant)
    await seed_facilitators_and_assets(tenant)
    await SignerAuthority().register_signer(tenant, "0xa11ce")
    plane = get_control_plane()

    auth = await _authorize_for(plane, tenant, resources, "0xnotregistered")
    result = await plane.verify_and_settle(tenant, auth.authorization_id, "0x" + "a" * 64)
    assert result["verified"] is False
    assert "not an active tenant-authorized signer" in result["error"]


@pytest.mark.asyncio
async def test_verify_and_settle_accepts_registered_payer():
    """The registered signer's own address verifies and settles normally."""
    from services.x402.control_plane import get_control_plane
    from services.x402.facilitators import seed_facilitators_and_assets
    from services.x402.resources import seed_aether_native_resources

    tenant = "t_signer_ok"
    resources = await seed_aether_native_resources(tenant)
    await seed_facilitators_and_assets(tenant)
    await SignerAuthority().register_signer(tenant, "0xa11ce")
    plane = get_control_plane()

    auth = await _authorize_for(plane, tenant, resources, "0xa11ce")
    result = await plane.verify_and_settle(tenant, auth.authorization_id, "0x" + "a" * 64)
    assert result["verified"] is True


@pytest.mark.asyncio
async def test_verify_and_settle_rejects_deactivated_payer():
    """A deactivated signer reference is rejected even though the tenant still
    has other active signers (count_active > 0 keeps enforcement engaged)."""
    from services.x402.control_plane import get_control_plane
    from services.x402.facilitators import seed_facilitators_and_assets
    from services.x402.resources import seed_aether_native_resources

    tenant = "t_signer_deact"
    resources = await seed_aether_native_resources(tenant)
    await seed_facilitators_and_assets(tenant)
    authority = SignerAuthority()
    active = await authority.register_signer(tenant, "0xa11ce")
    gone = await authority.register_signer(tenant, "0xgone")
    await authority.deactivate_signer(tenant, gone.signer_ref_id)
    assert await authority.count_active(tenant) == 1  # enforcement stays engaged
    plane = get_control_plane()

    # The deactivated signer's address is rejected.
    auth = await _authorize_for(plane, tenant, resources, "0xgone")
    result = await plane.verify_and_settle(tenant, auth.authorization_id, "0x" + "a" * 64)
    assert result["verified"] is False
    assert "not an active tenant-authorized signer" in result["error"]

    # The still-active signer's address verifies normally.
    auth2 = await _authorize_for(plane, tenant, resources, "0xa11ce")
    result2 = await plane.verify_and_settle(tenant, auth2.authorization_id, "0x" + "b" * 64)
    assert result2["verified"] is True


# ═══════════════════════════════════════════════════════════════════════════
# CONTROL-PLANE METERING INTEGRATION
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_full_lifecycle_writes_meter_records():
    from services.x402.control_plane import get_control_plane
    from services.x402.facilitators import seed_facilitators_and_assets
    from services.x402.resources import seed_aether_native_resources

    tenant = "t_meter"
    resources = await seed_aether_native_resources(tenant)
    await seed_facilitators_and_assets(tenant)
    plane = get_control_plane()
    r = resources[0]

    challenge = await plane.issue_challenge(
        tenant_id=tenant, resource_id=r.resource_id, requester_id="agent_1"
    )
    approval, _ = await plane.request_approval(tenant, challenge.challenge_id)
    await plane.apply_decision(tenant, approval.approval_id, "approve", "ops", "ok")
    auth = await plane.authorize_payment(tenant, approval.approval_id, "0xpayer")
    result = await plane.verify_and_settle(tenant, auth.authorization_id, "0x" + "a" * 64)
    assert result["verified"] is True
    await plane.grant_access(tenant, result["entitlement_id"])

    summary = await get_metering_service().summarize(tenant)
    assert summary["tenant_id"] == tenant
    by_type = summary["by_type"]
    assert by_type["challenge_issued"]["count"] == 1
    assert by_type["payment_paid"]["count"] == 1
    assert by_type["entitled"]["count"] == 1
    assert by_type["access_granted"]["count"] == 1
    assert by_type["payment_paid"]["amount_usd"] == r.price_usd
