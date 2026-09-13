"""Cross-cutting adversarial scenarios (program sec9/sec23).

Consolidated deterministic demonstrations of the shared fault vocabulary
across domains — each scenario asserts the fault is distinguishable from a
healthy empty result and that recovery is deterministic (no duplication, no
skip, no fabricated success):

  * credential expiry / rotation  — fail-closed on expiry, new secret visible
    immediately after rotation
  * cross-tenant isolation         — same basis under two tenants stays
    distinct; a foreign tenant can never release another tenant's reservation
  * wrong-environment separation   — staging registry never leaks into the
    production registry
  * cursor corruption              — a corrupted durable cursor restores to
    None and the worker resumes fresh (never wedges, never skips)
  * outbox publish failure → dead-letter — bounded retries then DLQ; the row
    is never silently dropped and never double-delivered
  * rollback / repair              — an operator replay of a dead-lettered
    payment receipt resumes the forward-only stage machine
  * reconciliation conflict        — a mismatched onchain match is MISMATCHED,
    never a fabricated MATCHED
  * store unavailable              — a failed receipt write never advances the
    stage machine, and the replay completes exactly once
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import SecretStr

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
ADV = Path(__file__).resolve().parent
if str(ADV) not in sys.path:
    sys.path.insert(0, str(ADV))

import faultkit  # noqa: E402
from faultkit import (  # noqa: E402
    BROKER_UNAVAILABLE,
    CREDENTIAL_EXPIRY,
    CREDENTIAL_ROTATION,
    CROSS_TENANT,
    CURSOR_CORRUPTION,
    DB_UNAVAILABLE,
    OUTBOX_PUBLISH_FAILURE,
    REDIS_UNAVAILABLE,
    REPAIR,
    WRONG_ENV,
    FaultyStore,
    arm,
    expect_fault,
    make_fault,
)
from repositories.repos import BaseRepository, reset_in_memory_stores  # noqa: E402
from repositories.stablecoin_repos import StablecoinObservationRepo  # noqa: E402
from repositories.typed_repo import reset_typed_in_memory_stores  # noqa: E402
from services.derivatives.guards import (  # noqa: E402
    CredentialNotUsable,
    resolve_read_only_credential,
)
from services.derivatives.durable_cursor import persist_connector_checkpoint  # noqa: E402
from services.derivatives.sequence import SupervisedStreamWorker, parse_stream_cursor  # noqa: E402
from services.derivatives.adapters.hyperliquid import HyperliquidAdapter  # noqa: E402
from services.integrations.providers.payment_rails.receipts import (  # noqa: E402
    ProviderReceiptRepository,
    ReceiptStage,
    ReceiptState,
)
from services.rewards.budget import BudgetReservationService  # noqa: E402
from services.stablecoin.models import StablecoinObservationIngest  # noqa: E402
from services.stablecoins.registry import PLATFORM_STABLECOIN_REGISTRY  # noqa: E402
from services.stablecoin.service import StablecoinObservationService  # noqa: E402
from services.stablecoins.reconciliation import (  # noqa: E402
    OnchainEvidence,
    PaymentIntentEvidence,
    ReconciliationState,
    StablecoinReconciliationService,
)
from shared.credentials.in_memory import InMemoryCredentialBackend  # noqa: E402
from shared.credentials.service import CredentialService  # noqa: E402
from shared.credentials.types import ApiKeyCredential, OAuthTokenCredential  # noqa: E402
from shared.outbox import GenericOutboxWorker  # noqa: E402


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()
    reset_typed_in_memory_stores()
    InMemoryCredentialBackend.reset()
    yield
    reset_in_memory_stores()
    reset_typed_in_memory_stores()
    InMemoryCredentialBackend.reset()


# ── credential expiry + rotation (1C) ────────────────────────────────────

@pytest.mark.asyncio
async def test_credential_expiry_fails_closed_and_rotation_is_immediate():
    svc = CredentialService(backend=InMemoryCredentialBackend())
    await svc.create(
        "t1",
        "expired-ref",
        OAuthTokenCredential(
            access_token=SecretStr("tok"),
            scope=["read"],
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        ),
    )
    exc = await expect_fault(
        resolve_read_only_credential("expired-ref", tenant_id="t1", service=svc),
        None,  # type is authoritative for this domain (CredentialNotUsable)
    )
    assert isinstance(exc, CredentialNotUsable)

    # Rotation: a fresh live credential resolves under the NEW secret at once.
    await svc.create("t1", "live-ref", ApiKeyCredential(api_key=SecretStr("v1-secret")))
    resolved = await resolve_read_only_credential("live-ref", tenant_id="t1", service=svc)
    assert resolved.api_key == "v1-secret"
    await svc.rotate("t1", "live-ref", ApiKeyCredential(api_key=SecretStr("v2-secret")))
    rotated = await resolve_read_only_credential("live-ref", tenant_id="t1", service=svc)
    assert rotated.api_key == "v2-secret"


# ── cross-tenant isolation ───────────────────────────────────────────────

async def _ingest(service, tenant_id: str, *, tx: str, amount_atomic: int) -> dict:
    ingest = StablecoinObservationIngest(
        observation_type="transfer",
        chain_id="8453",
        network="base-mainnet",
        transaction_hash=tx,
        contract_or_mint="0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        amount_atomic=amount_atomic,
        finality_status="finalized",
        observed_at="2026-08-09T00:00:00Z",
    )
    return await service.ingest_observation(tenant_id, ingest)


@pytest.mark.asyncio
async def test_cross_tenant_same_observation_stays_distinct_and_isolated():
    service = StablecoinObservationService()
    a = await _ingest(service, "tenant-a", tx="0xshared", amount_atomic=1000)
    b = await _ingest(service, "tenant-b", tx="0xshared", amount_atomic=1000)
    assert a["inserted"] is True and b["inserted"] is True

    repo = StablecoinObservationRepo()
    rows_a = await repo.find_many({"tenant_id": "tenant-a"}, limit=10)
    rows_b = await repo.find_many({"tenant_id": "tenant-b"}, limit=10)
    # Each tenant sees exactly its own row — no cross-tenant leakage.
    assert len(rows_a) == 1 and all(r["tenant_id"] == "tenant-a" for r in rows_a)
    assert len(rows_b) == 1 and all(r["tenant_id"] == "tenant-b" for r in rows_b)
    # The deterministic observation identity is tenant-independent, but the
    # idempotency conflict key is (tenant_id, idempotency_key), so the two
    # tenants' rows never collide and a replay under the SAME tenant collapses.
    assert rows_a[0]["observation_id"] == rows_b[0]["observation_id"]
    replay_a = await _ingest(service, "tenant-a", tx="0xshared", amount_atomic=1000)
    assert replay_a["inserted"] is False
    assert len(await repo.find_many({"tenant_id": "tenant-a"}, limit=10)) == 1


@pytest.mark.asyncio
async def test_cross_tenant_budget_release_is_forbidden():
    budget = BudgetReservationService()
    reserved = await budget.reserve(
        tenant_id="owner", campaign_id="camp-1", amount=Decimal("10"),
        cap=Decimal("100"), reservation_key="key-1",
    )
    assert reserved.ok is True

    # A foreign tenant cannot commit/release another tenant's reservation.
    release = await budget.release(reserved.reservation_id, tenant_id="intruder")
    assert release.ok is False and release.reason == "forbidden"
    # The owner's release still succeeds exactly once.
    owner = await budget.release(reserved.reservation_id, tenant_id="owner")
    assert owner.ok is True and owner.state == "released"
    replay = await budget.release(reserved.reservation_id, tenant_id="owner")
    assert replay.ok is True and replay.state == "released"


# ── wrong-environment separation ─────────────────────────────────────────

def test_wrong_environment_registry_separation():
    # PORT-ADAPT: main carries a single canonical platform registry (the
    # branch-only PLATFORM_STABLECOIN_REGISTRY_STAGING / resolve_platform_registry
    # were not ported). The wrong-environment invariant main enforces is that
    # the production registry contains ONLY issuer-verified mainnet deployments
    # — no testnet deployment can ever leak into the canonical registry.
    deployments = list(PLATFORM_STABLECOIN_REGISTRY.deployments.values())
    assert deployments, "expected at least one canonical stablecoin deployment"
    assert all(d.issuer_verified for d in deployments), (
        "unverified deployment leaked into the production registry"
    )
    assert all(not d.testnet for d in deployments), (
        "testnet deployment leaked into the production registry"
    )
    # No testnet/underlying network id appears in any canonical deployment.
    for d in deployments:
        assert "testnet" not in d.network and "sepolia" not in d.network


# ── cursor corruption ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cursor_corruption_restores_none_and_resumes_fresh():
    from repositories.derivatives_repos import ConnectorCheckpointRepo

    repo = ConnectorCheckpointRepo()
    await persist_connector_checkpoint(
        repo,
        tenant_id="t1",
        connector_id="hyperliquid",
        checkpoint_value="not-json{{{",
        advanced_at="2026-08-09T00:00:00Z",
        state="ok",
    )
    assert parse_stream_cursor("not-json{{{") is None  # bad row -> None, not wedge

    source = faultkit.PlanSource([faultkit.frame(1, {"fill_id": "f1"})])
    adapter = HyperliquidAdapter(stream_factory=source)
    worker = SupervisedStreamWorker(adapter, tenant_id="t1", connector_id="hyperliquid")
    assert await worker.restore_cursor() is None
    result = await worker.run_once()
    assert result.accepted == [{"fill_id": "f1"}]
    # The corrupted cursor never skips: the fresh start persisted a real cursor.
    assert await worker.restore_cursor() == 2


# ── outbox publish failure → dead-letter ─────────────────────────────────

@pytest.mark.asyncio
async def test_outbox_publish_failure_bounded_then_dead_lettered():
    repo = BaseRepository("adversarial_outbox")
    await repo.insert("row-1", {
        "id": "row-1", "tenant_id": "t1", "status": "queued", "attempts": 0,
        "created_at": "2026-08-09T00:00:00Z",
    })

    calls = {"n": 0}

    async def sink(row):
        calls["n"] += 1
        raise RuntimeError("broker publish rejected")  # every attempt fails

    worker = GenericOutboxWorker(
        repo, sink, name="adversarial-outbox", max_attempts=3,
        backoff_base_s=0.0,  # zero backoff -> retries are due on the next drain
    )
    # max_attempts=3 -> the 4th drain sees attempts >= max_attempts and
    # dead-letters the row (attempts is incremented by each sink call).
    for _ in range(4):
        summary = await worker.drain_once(tenant_id="t1")
    assert summary["dead_lettered"] == 1
    assert summary["succeeded"] == 0
    row = await repo.find_by_id("row-1")
    assert row["status"] == "dead_lettered"
    assert row["attempts"] == 3
    assert calls["n"] == 3  # every attempt was a real publish attempt


@pytest.mark.asyncio
async def test_outbox_failure_does_not_lose_row_and_recovers():
    repo = BaseRepository("adversarial_outbox")
    await repo.insert("row-2", {
        "id": "row-2", "tenant_id": "t2", "status": "queued", "attempts": 0,
        "created_at": "2026-08-09T00:00:00Z",
    })
    faults = {"n": 0}

    async def sink(row):
        faults["n"] += 1
        if faults["n"] == 1:
            raise RuntimeError("transient broker outage")
        row["delivered_ref"] = "ok"

    worker = GenericOutboxWorker(
        repo, sink, name="adversarial-outbox-2", max_attempts=5,
        backoff_base_s=0.0,  # zero backoff -> the retry is due on the next drain
    )
    first = await worker.drain_once(tenant_id="t2")
    assert first["failed"] == 1 and first["dead_lettered"] == 0
    row = await repo.find_by_id("row-2")
    assert row["status"] == "failed" and row["attempts"] == 1  # retried, not lost

    second = await worker.drain_once(tenant_id="t2")
    assert second["succeeded"] == 1
    row = await repo.find_by_id("row-2")
    assert row["status"] == "persisted" and row["delivered_ref"] == "ok"
    assert row["attempts"] == 2  # exactly one retry, no duplicate delivery


# ── rollback / repair of a dead-lettered payment receipt ─────────────────

@pytest.mark.asyncio
async def test_repair_resets_dead_lettered_receipt_into_recoverable_pipeline():
    repo = ProviderReceiptRepository()
    record = await repo.open(
        "t1", "moonpay", provider_event_id="evt-1", environment="production",
    )
    rid = record["receipt_id"]
    # Dead-lettered mid-delivery (e.g. outbox publish failed repeatedly).
    await repo.mark_state(
        "t1", rid, ReceiptState.DEAD_LETTERED,
        reason="outbox publish exhausted", error_classification=OUTBOX_PUBLISH_FAILURE,
    )
    dead = await repo.get("t1", rid)
    assert dead["current_stage"] == ReceiptState.DEAD_LETTERED

    # Operator replay (PORT-ADAPT: main dropped reset_repair; the canonical
    # recovery is mark_state(REPAIR_PENDING) + record_repair, which move the
    # dead-lettered receipt back into the recoverable pipeline and stamp the
    # replay in the auditable repair history).
    await repo.mark_state(
        "t1", rid, ReceiptState.REPAIR_PENDING, reason="key rotation applied",
    )
    await repo.record_repair(
        "t1", rid, outcome="operator_replay_reset", detail="key rotation applied",
    )
    repaired = await repo.get("t1", rid)
    assert repaired["current_stage"] == ReceiptState.REPAIR_PENDING
    assert repaired["rejection_reason"] == "key rotation applied"
    assert repaired["repair_history"][-1]["outcome"] == "operator_replay_reset"

    # The repaired receipt completes exactly once.
    await repo.advance("t1", rid, ReceiptStage.OUTBOX_PUBLISHED)
    await repo.advance("t1", rid, ReceiptStage.COMPLETED)
    final = await repo.get("t1", rid)
    assert final["current_stage"] == ReceiptStage.COMPLETED
    assert final["completed_at"] is not None

    # NOTE (adversarial finding): ProviderReceiptRepository.advance() computes
    # stage rank with ``_STAGE_RANK.get(current_stage, -1)``; terminal tokens
    # (REJECTED / QUARANTINED / DEAD_LETTERED) are NOT members of STAGE_ORDER,
    # so a stale re-observation calling advance() on a dead-lettered receipt
    # resurrects it to the requested stage instead of being refused. The repair
    # worker is the documented escape hatch; mark_state(REPAIR_PENDING) +
    # record_repair is the replay path. The advance-from-terminal gap is
    # flagged for the integration pass
    # (services/integrations/providers/payment_rails/receipts.py is outside
    # this agent's ownership).


# ── reconciliation conflict ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reconciliation_conflict_is_mismatched_never_fabricated_match():
    intent = PaymentIntentEvidence(
        tenant_id="t1", payment_intent_id="pi-1", expected_payer="0x" + "a" * 40,
        expected_recipient="0x" + "b" * 40, deployment_id="usdc:base:mainnet:x",
        chain_id="8453", amount_atomic=1_000_000,
    )
    # Wrong payer: the onchain sender is a DIFFERENT wallet than the tenant's
    # expected payer -> the identity conflicts, never a fabricated MATCHED.
    onchain = OnchainEvidence(
        transaction_hash="0xconflict", payer="0x" + "e" * 40,
        recipient="0x" + "b" * 40, deployment_id="usdc:base:mainnet:x",
        chain_id="8453", amount_atomic=1_000_000,
        finality_status="finalized",
    )
    service = StablecoinReconciliationService()
    result = await service.reconcile(intent, onchain)
    assert result.state == ReconciliationState.MISMATCHED  # conflict, not MATCHED
    assert "conflicts" in result.reason


# ── store unavailable: failed write never advances the stage machine ─────

@pytest.mark.asyncio
async def test_db_unavailable_write_never_advances_receipt_and_replays_exactly_once():
    repo = ProviderReceiptRepository()
    record = await repo.open("t1", "stripe_onramp", provider_event_id="evt-db", environment="production")
    rid = record["receipt_id"]

    # Arm the store so the NEXT write raises (simulated DB outage). The store
    # is wrapped in a CopyStore first so reads cross a serialization boundary
    # (faithful to a real DB): a failed write leaves durable state untouched.
    injector = faultkit.FaultInjector(make_fault(DB_UNAVAILABLE), mode="once")
    repo._store = FaultyStore(faultkit.CopyStore(repo._store), {"set": injector})

    with pytest.raises(Exception) as ei:
        await repo.advance("t1", rid, ReceiptStage.PARSED)
    assert faultkit.classify(ei.value) == DB_UNAVAILABLE
    # The stage machine did NOT advance on the failed write.
    assert (await repo.get("t1", rid))["current_stage"] == ReceiptStage.RECEIVED

    # Disarm (injector mode="once" already passed); replay completes.
    await repo.advance("t1", rid, ReceiptStage.PARSED)
    await repo.advance("t1", rid, ReceiptStage.NORMALIZED)
    await repo.advance("t1", rid, ReceiptStage.OUTBOX_PUBLISHED)
    await repo.advance("t1", rid, ReceiptStage.COMPLETED)
    final = await repo.get("t1", rid)
    assert final["current_stage"] == ReceiptStage.COMPLETED
    # Deterministic receipt identity: a provider retry maps to the same row.
    reopened = await repo.open("t1", "stripe_onramp", provider_event_id="evt-db", environment="production")
    assert reopened["receipt_id"] == rid
    assert reopened["current_stage"] == ReceiptStage.COMPLETED  # forward-only, no regression
